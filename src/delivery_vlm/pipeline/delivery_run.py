from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable
from pathlib import Path
from typing import Any

from delivery_vlm.config import load_config, project_root, vlm_settings
from delivery_vlm.delivery_schema import (
    attach_trace,
    delivery_columns_from_config,
    parse_delivery_response,
    xlsx_column_order,
)
from delivery_vlm.io.xlsx_delivery import write_delivery_rows_to_xlsx
from delivery_vlm.llm.client import OpenAICompatClient
from delivery_vlm.llm.retry import call_with_retries_timeout
from delivery_vlm.preprocess.image import preprocess_image
from delivery_vlm.prompts_loader import delivery_vlm_system, delivery_vlm_user
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
) -> dict[str, Any]:
    cfg = load_config(config_path)
    vs = vlm_settings()
    if not vs.get("api_key"):
        raise ValueError("未配置 VLM_API_KEY：请在 .env 中设置 VLM_BASE_URL 与 VLM_API_KEY")

    header_keys, line_keys = delivery_columns_from_config(cfg)
    columns = list(xlsx_column_order(header_keys, line_keys))

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
    api_key = str(vs.get("api_key"))
    base_url = vs.get("base_url") or None
    n_img = len(images)
    max_workers = _cap_workers(n_img, vlm.get("max_workers"))

    manifest_rows: list[dict[str, Any]] = []
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
        json_path = (base / f"{page_id}.json").resolve()
        json_path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rel_j = json_path.relative_to(out.resolve())
        man_row = {
            "page_id": page_id,
            "source_image": str(source_image.resolve()),
            "structured_file": str(rel_j).replace("\\", "/"),
            "excel_row_count": len(full_rows),
            "segment_count": len(biz_rows),
            "recognition": "vlm",
        }
        return json_path, man_row

    with tempfile.TemporaryDirectory(prefix="delivery_vlm_") as tmp:
        tdir = Path(tmp)
        _prog_lock = threading.Lock()
        _n_done = 0

        def _run_one(i: int, img_path: Path) -> tuple[int, dict[str, Any] | None, bool]:
            if cancel_event is not None and cancel_event.is_set():
                return (i, None, True)
            if _wait_unpaused(pause=paused, cancel=cancel_event):
                return (i, None, True)
            page_id = page_id_for(img_path, root=input_root)
            _log.info("[%s/%s] page_id=%s 文件=%s", i, n_img, page_id, img_path.name)
            if use_pre:
                pre_path = tdir / f"{page_id}.png"
                preprocess_image(
                    img_path,
                    pre_path,
                    max_long_edge=max_long_edge,
                    deskew=pre_cfg.get("deskew"),
                    tone_mode=str(pre_cfg.get("tone_mode", "raw")),
                    rotate_degrees=float(pre_cfg.get("rotate_degrees", 0.0) or 0.0),
                    auto_exif=bool(pre_cfg.get("auto_exif", True)),
                    auto_rotate=bool(pre_cfg.get("auto_rotate", False)),
                )
                body = pre_path.read_bytes()
                ctyp = "image/png"
            else:
                body = img_path.read_bytes()
                ctyp = _content_type(img_path.suffix)
            if cancel_event is not None and cancel_event.is_set():
                return (i, None, True)
            cl = OpenAICompatClient(api_key=api_key, base_url=base_url)
            raw = call_with_retries_timeout(
                lambda t: cl.chat_vision(
                    model=m_model,
                    system=p_sys,
                    user_text=p_user_template,
                    image_bytes=body,
                    content_type=ctyp,
                    temperature=temp,
                    timeout=float(t),
                    response_format_json=True,
                ),
                tries=3,
                base_timeout_s=float(timeout),
                base_sleep_s=1.0,
                on_retry=lambda att, e, s, nt: _log.warning(
                    "VLM HTTP 失败将重试 page_id=%s attempt=%s/3 sleep=%.2fs next_timeout=%.1fs err=%s: %s",
                    page_id,
                    att + 1,
                    s,
                    nt,
                    type(e).__name__,
                    e,
                ),
            )
            biz_rows, parse_meta = parse_delivery_response(
                raw, header_keys=header_keys, line_keys=line_keys
            )
            if parse_meta and parse_meta.get("parse_error"):
                _log.warning("page_id=%s 解析异常: %s", page_id, parse_meta)
            if not biz_rows and not (parse_meta and parse_meta.get("parse_error")):
                _log.warning("page_id=%s VLM 返回空行，原始前 800 字：%s", page_id, (raw or "")[:800])
            _, man_row = _export_page_json(
                page_id=page_id,
                source_image=img_path,
                raw_response=raw,
                biz_rows=biz_rows,
                parse_meta=parse_meta,
            )
            return (i, man_row, False)

        if max_workers <= 1:
            for i, img_path in enumerate(images, start=1):
                idx, row, aborted = _run_one(i, img_path)
                if row is None and aborted:
                    cancelled = True
                    break
                if row is not None:
                    _stream_manifest_row(idx, row)
                if on_page_done is not None:
                    on_page_done(i, n_img)
                if cancel_event is not None and cancel_event.is_set() and row is not None:
                    cancelled = True
                    break
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                pending = {ex.submit(_run_one, i, p): i for i, p in enumerate(images, start=1)}
                try:
                    for fut in as_completed(pending):
                        try:
                            _idx, row, _ab = fut.result()
                        except Exception:
                            ex.shutdown(wait=False, cancel_futures=True)
                            raise
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

    xlsx_path = (out_xlsx or (out / "delivery_merged.xlsx")).resolve()
    write_delivery_rows_to_xlsx(xlsx_path, all_rows, columns=columns)

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
        "n_rows": len(all_rows),
        "manifest": str(final_man_path or man_path),
        "out_xlsx": str(xlsx_path),
        "out_jsonl": str(jsonl_path) if jsonl_path else None,
        "model": m_model,
        "cancelled": cancelled,
    }
