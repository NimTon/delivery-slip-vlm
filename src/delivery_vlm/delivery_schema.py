from __future__ import annotations

from typing import Any

from delivery_vlm.llm.jsonutil import parse_json_object

# xlsx / excel_rows：原始输入图片绝对路径（文本）
XLSX_ORIGINAL_IMAGE_PATH_COLUMN = "原图路径"
# 明细 sheet 中用于插入缩略图的列名（单元格内嵌图，不写路径文本）
XLSX_ORIGINAL_IMAGE_EMBED_COLUMN = "原图"

TRACE_KEYS = ("page_id", XLSX_ORIGINAL_IMAGE_PATH_COLUMN)


# 默认：服装送货单式——无单独「表头」列，每行一款号多尺码数量 + 小计
DEFAULT_HEADER_KEYS: tuple[str, ...] = ()

DEFAULT_LINE_KEYS: tuple[str, ...] = (
    "款号",
    "颜色",
    "XS",
    "S",
    "M",
    "L",
    "XL",
    "XXL",
    "小计",
)


def delivery_merge_key_from_config(cfg: dict[str, Any]) -> str:
    """从配置读取合并键（默认：款号）。"""
    d = dict(cfg.get("delivery") or {})
    return str(d.get("merge_key") or "款号").strip() or "款号"


_VLM_ORIENTATION_TOP_KEYS = frozenset({"needs_rotation", "rotate_clockwise_90_steps", "rotate_degrees"})


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
    """明细 sheet：``page_id``、``原图路径``、嵌入列 ``原图``、再业务列。"""
    return tuple(TRACE_KEYS + (XLSX_ORIGINAL_IMAGE_EMBED_COLUMN,) + tuple(header_keys) + tuple(line_keys))


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
    return (XLSX_ORIGINAL_IMAGE_PATH_COLUMN,) + tuple(header_keys) + tuple(line_keys)


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


def fill_local_subtotals(rows: list[dict[str, Any]], *, line_keys: list[str]) -> list[dict[str, Any]]:
    """
    本地计算并填充每行「小计」：对尺码列求和。

    - 仅当 line_keys 中包含「小计」时生效
    - 尺码列默认取 line_keys 里出现的 XS/S/M/L/XL/XXL（可按需扩展）
    - 无法解析为数字的格按 0 处理；若该行所有尺码都为空则小计填 ""
    """
    if "小计" not in line_keys:
        return rows
    size_keys = [k for k in ("XS", "S", "M", "L", "XL", "XXL") if k in line_keys]
    if not size_keys:
        return rows

    for r in rows:
        if not isinstance(r, dict):
            continue
        total = 0
        any_val = False
        for k in size_keys:
            v = r.get(k, "")
            s = _as_str(v)
            if not s:
                continue
            any_val = True
            try:
                total += int(float(s.replace(",", "")))
            except ValueError:
                # 非数字按 0 处理
                continue
        r["小计"] = str(total) if any_val else ""
    return rows


def business_rows_as_strings(rows: list[dict[str, Any]], keys: list[str]) -> list[dict[str, str]]:
    """按给定键序投影为字符串单元格（用户模式、不合并时使用）。"""
    return [{k: _as_str(r.get(k, "")) for k in keys} for r in rows]


def merge_line_rows_by_style(
    rows: list[dict[str, Any]],
    *,
    header_keys: list[str],
    line_keys: list[str],
    merge_key: str = "款号",
    group_keys: list[str] | None = None,
) -> list[dict[str, str]]:
    """
    按给定分组键合并多行（默认按 ``merge_key``）。

    - 若分组键不包含「颜色」：颜色去重后用「；」串联；
    - 若分组键包含「颜色」：同款不同色会分开输出（颜色不再串联）。
    - 尺码/小计等按数值相加（无法解析则改拼接）。

    空 ``merge_key`` 的行互不合并（每行单独输出，款号格为空）。
    """
    keys_out = [XLSX_ORIGINAL_IMAGE_PATH_COLUMN] + list(header_keys) + list(line_keys)
    if merge_key not in line_keys:
        return [{k: _as_str(r.get(k, "")) for k in keys_out} for r in rows]

    gk = [merge_key] if not group_keys else [str(x).strip() for x in group_keys if str(x).strip()]
    # 只保留在 line_keys 中存在的分组键，且去重
    seen_gk: set[str] = set()
    group_keys2: list[str] = []
    for k in gk:
        if k in line_keys and k not in seen_gk:
            group_keys2.append(k)
            seen_gk.add(k)
    if not group_keys2:
        group_keys2 = [merge_key]

    order: list[str] = []
    buckets: dict[str, list[dict[str, Any]]] = {}
    display_for_bucket: dict[str, dict[str, str]] = {}

    for idx, r in enumerate(rows):
        vals = {k: _as_str(r.get(k)) for k in group_keys2}
        if any(vals.values()):
            bid = "||".join(f"{k}={vals.get(k,'')}" for k in group_keys2)
            disp = vals
        else:
            bid = f"__ungrouped_{idx}"
            disp = {k: "" for k in group_keys2}
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
        seen_paths: set[str] = set()
        paths: list[str] = []
        for r in grp:
            t = _as_str(r.get(XLSX_ORIGINAL_IMAGE_PATH_COLUMN))
            if t and t not in seen_paths:
                seen_paths.add(t)
                paths.append(t)
        row[XLSX_ORIGINAL_IMAGE_PATH_COLUMN] = "；".join(paths)
        disp = display_for_bucket.get(bid, {})
        for k in group_keys2:
            row[k] = _as_str(disp.get(k, ""))

        if "颜色" in line_keys and "颜色" not in group_keys2:
            seen: set[str] = set()
            colors: list[str] = []
            for r in grp:
                c = _as_str(r.get("颜色"))
                if c and c not in seen:
                    seen.add(c)
                    colors.append(c)
            row["颜色"] = "；".join(colors)
        for col in line_keys:
            if col in set(group_keys2) or (col == "颜色" and "颜色" not in group_keys2):
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
            v = _as_str(raw.get(k))
            # 约束：款号统一大写（避免 a01/A01 混用导致合并不稳定）
            if k == "款号" and v:
                v = v.upper()
            out[k] = v
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
    trace = {"page_id": page_id, XLSX_ORIGINAL_IMAGE_PATH_COLUMN: source_image}
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
    返回值为「仅业务列」的行列表（不含 page_id/原图路径），由调用方 attach_trace。

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
        source_image="__原图路径__",
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
        out.append({"page_id": page_id, XLSX_ORIGINAL_IMAGE_PATH_COLUMN: source_image, **h, **ln})
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


