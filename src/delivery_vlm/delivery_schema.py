from __future__ import annotations

from typing import Any

from delivery_vlm.llm.jsonutil import parse_json_object

TRACE_KEYS = ("page_id", "source_image")

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
    return tuple(TRACE_KEYS + tuple(header_keys) + tuple(line_keys))


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
