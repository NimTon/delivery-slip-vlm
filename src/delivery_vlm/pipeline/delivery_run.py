from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from delivery_vlm.config import deep_merge_config, load_config, project_root, vlm_settings
from delivery_vlm.delivery_schema import (
    attach_trace,
    delivery_columns_from_config,
    fill_local_subtotals,
    merge_line_rows_by_style,
    parse_delivery_response,
    xlsx_column_headers,
)
from delivery_vlm.io.xlsx_delivery import write_delivery_workbook_to_xlsx
from delivery_vlm.llm.client import OpenAICompatClient
from delivery_vlm.llm.retry import call_with_retries_timeout
from delivery_vlm.preprocess.geometry import load_bgr
from delivery_vlm.preprocess.image import preprocess_image
from delivery_vlm.prompts_loader import (
    delivery_vlm_system,
    delivery_vlm_user,
)
from delivery_vlm.pipeline.scan_pages import list_input_images, page_id_for

_log = logging.getLogger(__name__)


def _content_type(suffix: str) -> str:
    s = suffix.lower()
    if s == ".png":
        return "image/png"
    if s in (".jpg", ".jpeg"):
        return "image/jpeg"
    if s == ".bmp":
        return "image/bmp"
    if s == ".webp":
        return "image/webp"
    return "image/png"


def _resolve_max_long_edge(*, vlm: dict[str, Any], pre_cfg: dict[str, Any]) -> int:
    if "max_long_edge" in vlm and vlm["max_long_edge"] is not None:
        return int(vlm["max_long_edge"])
    m = pre_cfg.get("max_long_edge", 2000)
    return int(m) if m is not None else 2000


def _cap_workers(n_tasks: int, raw: Any) -> int:
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        w = min(32, (os.cpu_count() or 4) * 4)
    else:
        w = int(raw)
    w = max(1, w)
    return min(w, max(1, n_tasks))


def _prepare_run_temp_dir() -> Path:
    """保留本次临时图到下次运行；下次开始前清空。"""
    tdir = (project_root() / "data" / "tmp").resolve()
    if tdir.exists():
        shutil.rmtree(tdir, ignore_errors=True)
    tdir.mkdir(parents=True, exist_ok=True)
    return tdir


def _wait_unpaused(
    *, pause: Callable[[], bool] | None, cancel: threading.Event | None
) -> bool:
    while True:
        if cancel is not None and cancel.is_set():
            return True
        if pause is None or not pause():
            return False
        time.sleep(0.12)


def write_manifest(out: Path, subdir: str, manifest_name: str, rows: list[dict[str, Any]]) -> Path | None:
    if not rows:
        return None
    path = (out / subdir / manifest_name).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
    path.write_text(body, encoding="utf-8")
    return path


def run_delivery_vlm_to_xlsx(
    *,
    input_dir: Path,
    out_dir: Path | None = None,
    config_path: Path | None = None,
    model: str | None = None,
    out_xlsx: Path | None = None,
    out_jsonl: Path | None = None,
    cancel_event: threading.Event | None = None,
    paused: Callable[[], bool] | None = None,
    on_page_done: Callable[[int, int], None] | None = None,
    config_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = load_config(config_path)
    if config_overrides:
        cfg = deep_merge_config(cfg, config_overrides)
    vs = vlm_settings()
    if not vs.get("api_key"):
        raise ValueError("未配置 VLM_API_KEY：请在 .env 中设置 VLM_BASE_URL 与 VLM_API_KEY")

    header_keys, line_keys = delivery_columns_from_config(cfg)

    vlm = dict(cfg.get("vlm") or {})
    pre_cfg = dict(cfg.get("preprocess") or {})
    pt = dict(cfg.get("page_text") or {})
    subdir = str(pt.get("subdir", "pages"))
    manifest_name = str(pt.get("manifest", "pages.jsonl"))

    if (model or "").strip():
        m_model = (model or "").strip()
    elif (vlm.get("model") is not None) and str(vlm.get("model", "")).strip():
        m_model = str(vlm.get("model")).strip()
    else:
        m_model = str(vs.get("mm_model") or "gpt-4o")
    temp = float(vlm.get("temperature", 0.1))
    timeout = float(vlm.get("timeout_seconds", 300.0))
    use_pre = bool(vlm.get("use_preprocess", True))

    root = project_root()
    out = (out_dir or (root / "data" / "out" / "delivery_vlm")).resolve()
    out.mkdir(parents=True, exist_ok=True)

    max_long_edge = _resolve_max_long_edge(vlm=vlm, pre_cfg=pre_cfg)

    images = list_input_images(input_dir)
    if not images:
        raise FileNotFoundError(f"目录中未找到图片: {input_dir}")
    input_root = input_dir.resolve()

    p_sys = delivery_vlm_system()
    p_user_template = delivery_vlm_user(header_keys=header_keys, line_keys=line_keys)
    _log.info("VLM 单次识别模式（无朝向门控）")
    api_key = str(vs.get("api_key"))
    base_url = vs.get("base_url") or None
    n_img = len(images)
    max_workers = _cap_workers(n_img, vlm.get("max_workers"))

    manifest_rows: list[dict[str, Any]] = []
    failed_pages: list[dict[str, Any]] = []
    cancelled = False
    man_path = (out / subdir / manifest_name).resolve()
    man_path.parent.mkdir(parents=True, exist_ok=True)
    man_f = man_path.open("w", encoding="utf-8", newline="")
    _man_lock = threading.Lock()
    _pending_rows: dict[int, dict[str, Any]] = {}
    _next_write_idx = 1

    def _stream_manifest_row(idx: int, row: dict[str, Any]) -> None:
        nonlocal _next_write_idx
        with _man_lock:
            _pending_rows[idx] = row
            while _next_write_idx in _pending_rows:
                r = _pending_rows.pop(_next_write_idx)
                man_f.write(json.dumps(r, ensure_ascii=False) + "\n")
                man_f.flush()
                try:
                    os.fsync(man_f.fileno())
                except OSError:
                    pass
                manifest_rows.append(r)
                _log.info(
                    "delivery-vlm stream-saved [%s/%s] page_id=%s -> %s",
                    _next_write_idx,
                    n_img,
                    r.get("page_id", ""),
                    str(man_path),
                )
                _next_write_idx += 1

    def _export_page_json(
        *,
        page_id: str,
        source_image: Path,
        raw_response: str,
        biz_rows: list[dict[str, str]],
        parse_meta: dict[str, Any] | None,
        page_extras: dict[str, Any] | None = None,
    ) -> tuple[Path, dict[str, Any]]:
        base = out / subdir
        base.mkdir(parents=True, exist_ok=True)
        full_rows = attach_trace(
            biz_rows,
            page_id=page_id,
            source_image=str(source_image.resolve()),
            header_keys=header_keys,
            line_keys=line_keys,
        )
        body: dict[str, Any] = {
            "page_id": page_id,
            "source_image": str(source_image.resolve()),
            "header_keys": header_keys,
            "line_keys": line_keys,
            "excel_rows": full_rows,
            "parse_meta": parse_meta,
            "vlm_raw_preview": (raw_response or "")[:80000],
        }
        if page_extras:
            body.update(page_extras)
        json_path = (base / f"{page_id}.json").resolve()
        json_path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rel_j = json_path.relative_to(out.resolve())
        man_row: dict[str, Any] = {
            "page_id": page_id,
            "source_image": str(source_image.resolve()),
            "structured_file": str(rel_j).replace("\\", "/"),
            "excel_row_count": len(full_rows),
            "segment_count": len(biz_rows),
            "recognition": "vlm",
        }
        return json_path, man_row

    def _encode_png_bgr(bgr: np.ndarray) -> tuple[bytes, str]:
        ok, buf = cv2.imencode(".png", bgr)
        if not ok:
            raise RuntimeError("PNG 编码失败")
        return buf.tobytes(), "image/png"

    tdir = _prepare_run_temp_dir()
    _log.info("本次运行临时图片目录：%s（下次运行前会清空）", tdir)
    _prog_lock = threading.Lock()
    _n_done = 0

    def _run_one(i: int, img_path: Path) -> tuple[int, dict[str, Any] | None, bool]:
        if cancel_event is not None and cancel_event.is_set():
            return (i, None, True)
        if _wait_unpaused(pause=paused, cancel=cancel_event):
            return (i, None, True)
        page_id = page_id_for(img_path, root=input_root)
        _log.info("[%s/%s] page_id=%s 文件=%s", i, n_img, page_id, img_path.name)
        pre_path: Path | None = None
        img_work: np.ndarray | None = None
        if use_pre:
            pre_path = tdir / f"{page_id}.png"
            preprocess_image(
                img_path,
                pre_path,
                max_long_edge=max_long_edge,
                tone_mode=str(pre_cfg.get("tone_mode", "raw")),
                auto_exif=bool(pre_cfg.get("auto_exif", True)),
                perspective=pre_cfg.get("perspective"),
                auto_rotate_ocr=pre_cfg.get("auto_rotate_ocr"),
            )
            img_work = cv2.imread(str(pre_path), cv2.IMREAD_COLOR)
            if img_work is None:
                raise ValueError(f"无法读取预处理图: {pre_path}")
        else:
            img_work = load_bgr(img_path, auto_exif=bool(pre_cfg.get("auto_exif", True)))
        if cancel_event is not None and cancel_event.is_set():
            return (i, None, True)
        cl = OpenAICompatClient(api_key=api_key, base_url=base_url)

        def _vision(*, system: str, user_text: str, image_bytes: bytes, ctype: str) -> str:
            def _call_once(t: float) -> str:
                txt = cl.chat_vision(
                    model=m_model,
                    system=system,
                    user_text=user_text,
                    image_bytes=image_bytes,
                    content_type=ctype,
                    temperature=temp,
                    timeout=float(t),
                    # 兼容性：部分 OpenAI-Compatible（如 DashScope compatible-mode）对 response_format(json_object)
                    # 支持不稳定，可能导致 message.content 为空/异常；这里改为依赖提示词约束输出 JSON。
                    response_format_json=False,
                )
                if not (txt or "").strip():
                    raise RuntimeError("empty response body from vlm")
                return txt

            return call_with_retries_timeout(
                _call_once,
                tries=3,
                base_timeout_s=float(timeout),
                base_sleep_s=1.0,
                on_retry=lambda att, e, s, nt: _log.warning(
                    "VLM 调用失败将重试 page_id=%s attempt=%s/3 sleep=%.2fs next_timeout=%.1fs err=%s: %s",
                    page_id,
                    att + 1,
                    s,
                    nt,
                    type(e).__name__,
                    e,
                ),
            )

        raw_final: str
        if use_pre and pre_path is not None:
            body = pre_path.read_bytes()
            ctyp = "image/png"
        else:
            body = img_path.read_bytes()
            ctyp = _content_type(img_path.suffix)
        raw_final = _vision(
            system=p_sys,
            user_text=p_user_template,
            image_bytes=body,
            ctype=ctyp,
        )

        biz_rows, parse_meta = parse_delivery_response(
            raw_final,
            header_keys=header_keys,
            line_keys=line_keys,
            drop_vlm_orientation_keys=True,
        )
        # 小计本地计算：不依赖 VLM 识别
        fill_local_subtotals(biz_rows, line_keys=line_keys)
        if parse_meta and parse_meta.get("parse_error"):
            _log.warning("page_id=%s 解析异常: %s", page_id, parse_meta)
            if parse_meta.get("parse_error") == "json":
                raw_show = (raw_final or "")[:2000]
                _log.warning(
                    "page_id=%s JSON解析原始返回 len=%s repr=%r",
                    page_id,
                    len(raw_final or ""),
                    raw_show,
                )
        if not biz_rows and not (parse_meta and parse_meta.get("parse_error")):
            _log.warning("page_id=%s VLM 返回空行，原始前 800 字：%s", page_id, (raw_final or "")[:800])
        _, man_row = _export_page_json(
            page_id=page_id,
            source_image=img_path,
            raw_response=raw_final,
            biz_rows=biz_rows,
            parse_meta=parse_meta,
            page_extras=None,
        )
        return (i, man_row, False)

    def _run_one_with_retry(
        i: int, img_path: Path
    ) -> tuple[int, dict[str, Any] | None, bool, dict[str, Any] | None]:
        page_id = page_id_for(img_path, root=input_root)
        for attempt in range(1, 4):
            if cancel_event is not None and cancel_event.is_set():
                return (i, None, True, None)
            try:
                idx, row, aborted = _run_one(i, img_path)
                return (idx, row, aborted, None)
            except Exception as e:  # noqa: BLE001
                if attempt < 3:
                    _log.warning(
                        "page_id=%s 识别失败将重试 attempt=%s/3 err=%s: %s",
                        page_id,
                        attempt + 1,
                        type(e).__name__,
                        e,
                    )
                    time.sleep(0.4 * attempt)
                    continue
                err_txt = f"{type(e).__name__}: {e}"
                _log.error("page_id=%s 识别失败已跳过（3次仍失败）err=%s", page_id, err_txt)
                return (
                    i,
                    None,
                    False,
                    {
                        "page_id": page_id,
                        "source_image": str(img_path.resolve()),
                        "attempts": attempt,
                        "error": err_txt,
                    },
                )
        return (i, None, False, None)

    if max_workers <= 1:
        for i, img_path in enumerate(images, start=1):
            idx, row, aborted, fail_info = _run_one_with_retry(i, img_path)
            if row is None and aborted:
                cancelled = True
                break
            if fail_info is not None:
                failed_pages.append(fail_info)
            if row is not None:
                _stream_manifest_row(idx, row)
            if on_page_done is not None:
                on_page_done(i, n_img)
            if cancel_event is not None and cancel_event.is_set() and row is not None:
                cancelled = True
                break
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            pending = {ex.submit(_run_one_with_retry, i, p): i for i, p in enumerate(images, start=1)}
            try:
                for fut in as_completed(pending):
                    try:
                        _idx, row, _ab, fail_info = fut.result()
                    except Exception:
                        ex.shutdown(wait=False, cancel_futures=True)
                        raise
                    if fail_info is not None:
                        failed_pages.append(fail_info)
                    if row is not None:
                        _stream_manifest_row(_idx, row)
                    if on_page_done is not None:
                        with _prog_lock:
                            _n_done += 1
                            c = _n_done
                        on_page_done(c, n_img)
            except Exception:
                raise
        if len(manifest_rows) < n_img and cancel_event is not None and cancel_event.is_set():
            cancelled = True

    try:
        man_f.close()
    except OSError:
        pass

    final_man_path = write_manifest(out, subdir, manifest_name, manifest_rows)
    tmp_png_count = len(list(tdir.glob("*.png")))
    if n_img > 0 and len(manifest_rows) == 0 and not cancelled and not failed_pages:
        _log.warning(
            "未产出任何页面结果：n_total_images=%s n_pages=%s use_preprocess=%s tmp_dir=%s tmp_png_count=%s",
            n_img,
            len(manifest_rows),
            use_pre,
            str(tdir),
            tmp_png_count,
        )
        cancelled = True
    if failed_pages:
        _log.warning("本次共跳过失败图片 %s 张", len(failed_pages))

    all_rows: list[dict[str, Any]] = []
    for r in manifest_rows:
        sf = r.get("structured_file")
        if not sf:
            continue
        jp = out / str(sf).replace("/", os.sep)
        if not jp.is_file():
            continue
        try:
            data = json.loads(jp.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            _log.warning("跳过损坏的 JSON %s: %s", jp, e)
            continue
        for er in data.get("excel_rows") or []:
            if isinstance(er, dict):
                all_rows.append(er)

    # 固定输出两个 sheet：
    # 1) detail：全明细 + 追溯列
    # 2) merged：按 merge_key 合并后的业务列
    dcfg = dict(cfg.get("delivery") or {})
    merge_key = str(dcfg.get("merge_key") or "款号").strip() or "款号"

    columns_detail = list(xlsx_column_headers(dev=True, header_keys=header_keys, line_keys=line_keys))
    columns_merged = list(xlsx_column_headers(dev=False, header_keys=header_keys, line_keys=line_keys))
    keys_biz = header_keys + line_keys
    rows_detail = all_rows
    biz_rows = [{k: r.get(k, "") for k in keys_biz} for r in all_rows]
    rows_merged = merge_line_rows_by_style(
        biz_rows,
        header_keys=header_keys,
        line_keys=line_keys,
        merge_key=merge_key,
        group_keys=[merge_key, "颜色"] if "颜色" in line_keys and merge_key != "颜色" else [merge_key],
    )

    xlsx_path = (out_xlsx or (out / "delivery_merged.xlsx")).resolve()
    write_delivery_workbook_to_xlsx(
        xlsx_path,
        sheets=[
            ("detail", rows_detail, columns_detail),
            ("merged", rows_merged, columns_merged),
        ],
    )

    jsonl_path = None
    if out_jsonl is not None:
        jsonl_path = out_jsonl.resolve()
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with jsonl_path.open("w", encoding="utf-8", newline="") as jf:
            for row in all_rows:
                jf.write(json.dumps(row, ensure_ascii=False) + "\n")

    return {
        "mode": "delivery_vlm",
        "out_dir": str(out),
        "n_pages": len(manifest_rows),
        "n_total_images": len(images),
        "n_rows": len(rows_merged),
        "n_detail_rows": len(all_rows),
        "xlsx_sheets": ["detail", "merged"],
        "manifest": str(final_man_path or man_path),
        "out_xlsx": str(xlsx_path),
        "out_jsonl": str(jsonl_path) if jsonl_path else None,
        "model": m_model,
        "cancelled": cancelled,
        "n_failed_images": len(failed_pages),
        "failed_pages": failed_pages,
        "tmp_dir": str(tdir),
        "tmp_png_count": tmp_png_count,
    }
