from __future__ import annotations

from delivery_vlm.delivery_schema import (
    attach_trace,
    delivery_columns_from_config,
    fill_local_subtotals,
    merge_line_rows_by_style,
    parse_delivery_response,
    xlsx_column_headers,
)


def test_parse_header_lines_apparel() -> None:
    hk: list[str] = []
    lk = ["款号", "颜色", "S", "M", "L", "XL", "XXL", "小计"]
    raw = """
    {"lines":[
      {"款号":"A01","颜色":"黑","S":"1","M":"2","L":"0","XL":"","XXL":"","小计":"3"}
    ]}
    """
    rows, meta = parse_delivery_response(raw, header_keys=hk, line_keys=lk)
    assert meta is None or "parse_error" not in (meta or {})
    assert len(rows) == 1
    assert rows[0]["款号"] == "A01"
    assert rows[0]["小计"] == "3"
    full = attach_trace(rows, page_id="p1", source_image="/x/a.png", header_keys=hk, line_keys=lk)
    assert full[0]["page_id"] == "p1"
    assert full[0]["M"] == "2"


def test_parse_items_mode_apparel() -> None:
    hk: list[str] = []
    lk = ["款号", "颜色", "S", "M", "L", "XL", "XXL", "小计"]
    raw = '{"items":[{"款号":"B2","颜色":"白","S":"","M":"","L":"5","XL":"","XXL":"","小计":"5"}]}'
    rows, meta = parse_delivery_response(raw, header_keys=hk, line_keys=lk)
    assert len(rows) == 1
    assert rows[0]["颜色"] == "白"


def test_parse_invalid_json() -> None:
    hk = ["款号"]
    lk = ["S"]
    rows, meta = parse_delivery_response("not json", header_keys=hk, line_keys=lk)
    assert rows == []
    assert meta is not None and meta.get("parse_error") == "json"


def test_columns_from_config_default_apparel() -> None:
    cfg = {"delivery": {}}
    hk, lk = delivery_columns_from_config(cfg)
    assert hk == []
    assert "款号" in lk
    assert "XXL" in lk
    assert lk.index("小计") == len(lk) - 1


def test_columns_explicit_empty_header_in_yaml() -> None:
    cfg = {"delivery": {"header_keys": [], "line_keys": ["款号", "颜色", "XS", "S", "M", "L", "XL", "XXL", "小计"]}}
    hk, lk = delivery_columns_from_config(cfg)
    assert hk == []
    assert len(lk) == 9


def test_merge_by_style_sums_sizes() -> None:
    hk: list[str] = []
    lk = ["款号", "颜色", "XS", "S", "M", "L", "XL", "XXL", "小计"]
    rows = [
        {"款号": "A", "颜色": "红", "XS": "", "S": "1", "M": "2", "L": "", "XL": "", "XXL": "", "小计": "3"},
        {"款号": "A", "颜色": "黑", "XS": "", "S": "0", "M": "1", "L": "4", "XL": "", "XXL": "", "小计": "5"},
    ]
    out = merge_line_rows_by_style(rows, header_keys=hk, line_keys=lk, merge_key="款号", group_keys=["款号", "颜色"])
    # 按 款号+颜色 分组：同款不同色分开
    assert len(out) == 2
    out = sorted(out, key=lambda r: (r.get("款号", ""), r.get("颜色", "")))
    assert out[0]["款号"] == "A" and out[0]["颜色"] == "红"
    assert out[0]["S"] == "1"
    assert out[0]["M"] == "2"
    assert out[0]["L"] == ""
    assert out[0]["小计"] == "3"
    assert out[1]["款号"] == "A" and out[1]["颜色"] == "黑"
    assert out[1]["S"] == "0"
    assert out[1]["M"] == "1"
    assert out[1]["L"] == "4"
    assert out[1]["小计"] == "5"


def test_xlsx_user_columns_no_trace() -> None:
    hk: list[str] = []
    lk = ["款号", "颜色", "S"]
    assert xlsx_column_headers(dev=False, header_keys=hk, line_keys=lk) == ("款号", "颜色", "S")
    assert xlsx_column_headers(dev=True, header_keys=hk, line_keys=lk)[:2] == ("page_id", "source_image")


def test_drop_vlm_orientation_keys_smoke() -> None:
    hk: list[str] = []
    lk = ["款号", "颜色", "XS", "S", "M", "L", "XL", "XXL", "小计"]
    raw = '{"needs_rotation": true, "rotate_clockwise_90_steps": 1, "lines":[{"款号":"A","颜色":"","XS":"","S":"","M":"","L":"","XL":"","XXL":"","小计":""}]}'
    rows, meta = parse_delivery_response(raw, header_keys=hk, line_keys=lk, drop_vlm_orientation_keys=True)
    assert len(rows) == 1
    assert meta is None or "parse_error" not in (meta or {})


def test_fill_local_subtotals() -> None:
    lk = ["款号", "颜色", "XS", "S", "M", "L", "XL", "XXL", "小计"]
    rows = [
        {"款号": "A", "颜色": "红", "XS": "1", "S": "", "M": "2", "L": "0", "XL": "", "XXL": "", "小计": "999"},
        {"款号": "B", "颜色": "黑", "XS": "", "S": "", "M": "", "L": "", "XL": "", "XXL": "", "小计": "5"},
    ]
    fill_local_subtotals(rows, line_keys=lk)
    assert rows[0]["小计"] == "3"
    assert rows[1]["小计"] == ""
