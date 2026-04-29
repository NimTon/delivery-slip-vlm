from __future__ import annotations

from typing import Any

from delivery_vlm.llm.jsonutil import parse_json_object

TRACE_KEYS = ("page_id", "source_image")

_VLM_ORIENTATION_TOP_KEYS = frozenset({"needs_rotation", "rotate_clockwise_90_steps", "rotate_degrees"})

# 默认：服装送货单式——无单独「表头」列，每行一款号多尺码数量 + 小计
DEFAULT_HEADER_KEYS: tuple[str, ...] = ()

DEFAULT_LINE_KEYS: tuple[str, ...] = (
    "款号",
    "颜色",
    "S",
    "M",
    "L",
    "XL",
    "XXL",
    "小计",
)


def delivery_xlsx_options(cfg: dict[str, Any]) -> tuple[bool, str]:
    """
    从配置读取 xlsx 导出策略。

    返回 ``(merge_by_style, merge_key)``。
    - ``merge_by_style`` 为真：仅业务列，按 ``merge_key`` 分组合并。
    - 为假：输出全明细，且列中含 ``page_id`` / ``source_image``（不合并）。

    未写 ``merge_by_style`` 时，若存在已弃用的 ``xlsx_include_trace`` / ``xlsx_mode``，则按其推断是否合并。
    """
    d = dict(cfg.get("delivery") or {})
    if "merge_by_style" in d:
        merge_by_style = bool(d["merge_by_style"])
    else:
        if d.get("xlsx_include_trace") is True or xlsx_mode_is_dev(d.get("xlsx_mode")):
            merge_by_style = False
        else:
            merge_by_style = True
    mk = str(d.get("merge_key") or "款号").strip() or "款号"
    return merge_by_style, mk


def vlm_use_rotation_gate_from_config(vlm: dict[str, Any] | None) -> bool:
    """是否启用 VLM 朝向门控（多轮判定 + 按模型建议旋转后再识别）。"""
    if not vlm:
        return True
    if "use_vlm_rotation_gate" in vlm:
        return bool(vlm["use_vlm_rotation_gate"])
    if "orientation_gate" in vlm:
        return bool(vlm["orientation_gate"])
    return True


def delivery_columns_from_config(cfg: dict[str, Any]) -> tuple[list[str], list[str]]:
    d = cfg.get("delivery") or {}
    if "header_keys" in d:
        hk = d.get("header_keys")
        if isinstance(hk, list) and all(isinstance(x, str) for x in hk):
            header_keys = [str(x).strip() for x in hk if str(x).strip()]
        else:
            header_keys = []
    else:
        header_keys = list(DEFAULT_HEADER_KEYS)

    if "line_keys" in d:
        lk = d.get("line_keys")
        if isinstance(lk, list) and all(isinstance(x, str) for x in lk):
            line_keys = [str(x).strip() for x in lk if str(x).strip()]
            if not line_keys:
                line_keys = list(DEFAULT_LINE_KEYS)
        else:
            line_keys = list(DEFAULT_LINE_KEYS)
    else:
        line_keys = list(DEFAULT_LINE_KEYS)
    return header_keys, line_keys


def xlsx_column_order(header_keys: list[str], line_keys: list[str]) -> tuple[str, ...]:
    """含 ``page_id`` / ``source_image`` 的列序（开发/排错用）。"""
    return tuple(TRACE_KEYS + tuple(header_keys) + tuple(line_keys))


def xlsx_mode_is_dev(mode: str | None) -> bool:
    m = str(mode or "user").lower().strip()
    return m in ("dev", "debug", "full", "trace")


def xlsx_column_headers(
    *,
    dev: bool,
    header_keys: list[str],
    line_keys: list[str],
) -> tuple[str, ...]:
    """写入 xlsx 的表头列序：``dev`` 时含追溯列，否则仅业务列。"""
    if dev:
        return xlsx_column_order(header_keys, line_keys)
    return tuple(header_keys) + tuple(line_keys)


def _aggregate_quantity_cells(values: list[Any]) -> str:
    """多格合并：能解析为数字则求和，否则去重后用「；」拼接。"""
    parts = [_as_str(v) for v in values if _as_str(v)]
    if not parts:
        return ""
    nums: list[int] = []
    for t in parts:
        try:
            nums.append(int(float(t.replace(",", ""))))
        except ValueError:
            return "；".join(dict.fromkeys(parts))
    return str(sum(nums))


def business_rows_as_strings(rows: list[dict[str, Any]], keys: list[str]) -> list[dict[str, str]]:
    """按给定键序投影为字符串单元格（用户模式、不合并时使用）。"""
    return [{k: _as_str(r.get(k, "")) for k in keys} for r in rows]


def merge_line_rows_by_style(
    rows: list[dict[str, Any]],
    *,
    header_keys: list[str],
    line_keys: list[str],
    merge_key: str = "款号",
) -> list[dict[str, str]]:
    """
    按 ``merge_key``（默认款号）分组合并多行：颜色去重串联；尺码/小计等按数值相加（无法解析则改拼接）。

    空 ``merge_key`` 的行互不合并（每行单独输出，款号格为空）。
    """
    keys_out = list(header_keys) + list(line_keys)
    if merge_key not in line_keys:
        return [{k: _as_str(r.get(k, "")) for k in keys_out} for r in rows]

    order: list[str] = []
    buckets: dict[str, list[dict[str, Any]]] = {}
    display_for_bucket: dict[str, str] = {}

    for idx, r in enumerate(rows):
        raw_k = _as_str(r.get(merge_key))
        if raw_k:
            bid = raw_k
            disp = raw_k
        else:
            bid = f"__ungrouped_{idx}"
            disp = ""
        if bid not in buckets:
            buckets[bid] = []
            order.append(bid)
            display_for_bucket[bid] = disp
        buckets[bid].append(r)

    out: list[dict[str, str]] = []
    for bid in order:
        grp = buckets[bid]
        row: dict[str, str] = {}
        for hk in header_keys:
            v = ""
            for r in grp:
                t = _as_str(r.get(hk))
                if t:
                    v = t
                    break
            row[hk] = v
        row[merge_key] = display_for_bucket.get(bid, "")
        if "颜色" in line_keys:
            seen: set[str] = set()
            colors: list[str] = []
            for r in grp:
                c = _as_str(r.get("颜色"))
                if c and c not in seen:
                    seen.add(c)
                    colors.append(c)
            row["颜色"] = "；".join(colors)
        for col in line_keys:
            if col in (merge_key, "颜色"):
                continue
            row[col] = _aggregate_quantity_cells([r.get(col, "") for r in grp])
        out.append(row)
    return out


def _as_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.replace("\r\n", "\n").strip()
    return str(v).strip()


def _blank_header(header_keys: list[str]) -> dict[str, str]:
    return {k: "" for k in header_keys}


def _blank_line(line_keys: list[str]) -> dict[str, str]:
    return {k: "" for k in line_keys}


def _normalize_header(raw: Any, header_keys: list[str]) -> dict[str, str]:
    out = _blank_header(header_keys)
    if not isinstance(raw, dict):
        return out
    for k in header_keys:
        if k in raw:
            out[k] = _as_str(raw.get(k))
    return out


def _normalize_line(raw: Any, line_keys: list[str]) -> dict[str, str]:
    out = _blank_line(line_keys)
    if not isinstance(raw, dict):
        return out
    for k in line_keys:
        if k in raw:
            out[k] = _as_str(raw.get(k))
    return out


def merge_to_excel_rows(
    *,
    header: dict[str, str],
    lines: list[dict[str, str]],
    header_keys: list[str],
    line_keys: list[str],
    page_id: str,
    source_image: str,
) -> list[dict[str, str]]:
    """表头 + 多行明细展开为多行 xlsx 记录（每行含追溯列）。"""
    h = {k: header.get(k, "") for k in header_keys}
    trace = {"page_id": page_id, "source_image": source_image}
    if not lines:
        row: dict[str, str] = {**trace, **h, **_blank_line(line_keys)}
        return [row]
    out: list[dict[str, str]] = []
    for ln in lines:
        out.append({**trace, **h, **ln})
    return out


def parse_delivery_response(
    raw: str,
    *,
    header_keys: list[str],
    line_keys: list[str],
    drop_vlm_orientation_keys: bool = False,
) -> tuple[list[dict[str, str]], dict[str, Any] | None]:
    """
    解析 VLM 返回的 JSON。
    返回值为「仅业务列」的行列表（不含 page_id/source_image），由调用方 attach_trace。

    支持：
    - {\"header\": {...}, \"lines\": [{...}, ...]} 或 \"明细\" 代替 lines
    - {\"items\": [...]}：每项为一行，字段可同时含表头键与明细键
    """
    s = raw.strip()
    if s.startswith("```"):
        lines = s.split("\n")
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()

    meta: dict[str, Any] | None = None

    try:
        data = parse_json_object(s)
    except Exception as e:  # noqa: BLE001
        return [], {"parse_error": "json", "detail": str(e), "raw_preview": raw[:10000]}

    if not isinstance(data, dict):
        return [], {"parse_error": "not_object", "raw_preview": raw[:10000]}

    if drop_vlm_orientation_keys:
        data = {k: v for k, v in data.items() if k not in _VLM_ORIENTATION_TOP_KEYS}

    items = data.get("items")
    raw_lines: Any = None
    if "lines" in data:
        raw_lines = data.get("lines")
    elif isinstance(data.get("明细"), list):
        raw_lines = data.get("明细")

    has_lines_key = "lines" in data or "明细" in data
    use_items = (
        (not has_lines_key)
        and isinstance(items, list)
        and len(items) > 0
    )

    if use_items:
        biz_rows: list[dict[str, str]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            hdr = _normalize_header(it, header_keys)
            ln = _normalize_line(it, line_keys)
            biz_rows.append({**hdr, **ln})
        return biz_rows, meta

    hdr_raw = data.get("header")
    if hdr_raw is None and isinstance(data.get("表头"), dict):
        hdr_raw = data.get("表头")
    header = _normalize_header(hdr_raw, header_keys)

    norm_lines: list[dict[str, str]] = []
    if isinstance(raw_lines, list):
        for x in raw_lines:
            norm_lines.append(_normalize_line(x, line_keys))
    elif raw_lines is not None:
        meta = {"warning": "lines_not_list"}

    full = merge_to_excel_rows(
        header=header,
        lines=norm_lines,
        header_keys=header_keys,
        line_keys=line_keys,
        page_id="__p__",
        source_image="__s__",
    )
    biz_only: list[dict[str, str]] = []
    for r in full:
        d = {k: r[k] for k in header_keys + line_keys}
        biz_only.append(d)
    return biz_only, meta


def attach_trace(rows: list[dict[str, str]], *, page_id: str, source_image: str, header_keys: list[str], line_keys: list[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for r in rows:
        h = {k: r.get(k, "") for k in header_keys}
        ln = {k: r.get(k, "") for k in line_keys}
        out.append({"page_id": page_id, "source_image": source_image, **h, **ln})
    return out


def _strip_json_fence(raw: str) -> str:
    s = raw.strip()
    if s.startswith("```"):
        lines = s.split("\n")
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    return s


def extract_rotation_cw90_steps(data: dict[str, Any]) -> int:
    """从门控 JSON 取顺时针 90° 步数 0–3（与 ``rotate_90_bgr(img, k)`` 的 k 一致）。"""
    if "rotate_clockwise_90_steps" in data:
        try:
            return int(data["rotate_clockwise_90_steps"]) % 4
        except Exception:  # noqa: BLE001
            return 0
    if "rotate_degrees" in data:
        try:
            d = float(data["rotate_degrees"])
            k = int(round(d / 90.0)) % 4
            return k
        except Exception:  # noqa: BLE001
            return 0
    return 0


def parse_vlm_orientation_gate_response(raw: str) -> tuple[str, dict[str, Any]]:
    """
    解析「朝向门控 + 识别」合一的首轮 VLM JSON。

    返回 ``("rotate", {"steps": int, "raw": str})`` 或 ``("recognition", {"raw": str})``。
    - 当 ``needs_rotation`` 为真且顺时针步数非 0 时为 rotate（仅旋转、勿输出表格）。
    - 否则按正常识别 JSON 处理（同一次回复中的 lines/items）。
    """
    s = _strip_json_fence(raw)
    try:
        data = parse_json_object(s)
    except Exception:  # noqa: BLE001
        return "recognition", {"raw": raw}

    if not isinstance(data, dict):
        return "recognition", {"raw": raw}

    nr = data.get("needs_rotation")
    is_rotate = nr is True or (isinstance(nr, str) and nr.strip().lower() in ("true", "yes", "是", "1"))
    if not is_rotate:
        return "recognition", {"raw": raw}

    steps = extract_rotation_cw90_steps(data)
    if steps == 0:
        return "recognition", {"raw": raw}

    return "rotate", {"steps": steps, "raw": raw}
