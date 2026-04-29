from __future__ import annotations

from delivery_vlm.delivery_schema import (
    attach_trace,
    delivery_columns_from_config,
    delivery_xlsx_options,
    merge_line_rows_by_style,
    parse_delivery_response,
    vlm_use_rotation_gate_from_config,
    xlsx_column_headers,
    xlsx_mode_is_dev,
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
    cfg = {"delivery": {"header_keys": [], "line_keys": ["款号", "颜色", "S", "M", "L", "XL", "XXL", "小计"]}}
    hk, lk = delivery_columns_from_config(cfg)
    assert hk == []
    assert len(lk) == 8


def test_merge_by_style_sums_sizes() -> None:
    hk: list[str] = []
    lk = ["款号", "颜色", "S", "M", "L", "XL", "XXL", "小计"]
    rows = [
        {"款号": "A", "颜色": "红", "S": "1", "M": "2", "L": "", "XL": "", "XXL": "", "小计": "3"},
        {"款号": "A", "颜色": "黑", "S": "0", "M": "1", "L": "4", "XL": "", "XXL": "", "小计": "5"},
    ]
    out = merge_line_rows_by_style(rows, header_keys=hk, line_keys=lk, merge_key="款号")
    assert len(out) == 1
    assert out[0]["款号"] == "A"
    assert out[0]["颜色"] == "红；黑"
    assert out[0]["S"] == "1"
    assert out[0]["M"] == "3"
    assert out[0]["L"] == "4"
    assert out[0]["小计"] == "8"


def test_xlsx_user_columns_no_trace() -> None:
    hk: list[str] = []
    lk = ["款号", "颜色", "S"]
    assert xlsx_column_headers(dev=False, header_keys=hk, line_keys=lk) == ("款号", "颜色", "S")
    assert xlsx_column_headers(dev=True, header_keys=hk, line_keys=lk)[:2] == ("page_id", "source_image")


def test_delivery_xlsx_options_default_user() -> None:
    merge, mk = delivery_xlsx_options({"delivery": {}})
    assert merge is True
    assert mk == "款号"


def test_xlsx_mode_is_dev() -> None:
    assert xlsx_mode_is_dev("dev") is True
    assert xlsx_mode_is_dev("user") is False


def test_delivery_xlsx_options_no_merge_has_trace_semantics() -> None:
    merge, mk = delivery_xlsx_options({"delivery": {"merge_by_style": False, "merge_key": "款号"}})
    assert merge is False
    assert mk == "款号"


def test_delivery_xlsx_options_legacy_xlsx_include_trace() -> None:
    merge, _ = delivery_xlsx_options({"delivery": {"xlsx_include_trace": True}})
    assert merge is False


def test_delivery_xlsx_options_legacy_xlsx_mode() -> None:
    merge, _ = delivery_xlsx_options({"delivery": {"xlsx_mode": "dev"}})
    assert merge is False


def test_delivery_xlsx_options_merge_wins_over_legacy_trace() -> None:
    merge, _ = delivery_xlsx_options({"delivery": {"merge_by_style": True, "xlsx_include_trace": True}})
    assert merge is True


def test_vlm_use_rotation_gate_from_config() -> None:
    assert vlm_use_rotation_gate_from_config({}) is True
    assert vlm_use_rotation_gate_from_config({"orientation_gate": False}) is False
    assert vlm_use_rotation_gate_from_config({"use_vlm_rotation_gate": False, "orientation_gate": True}) is False
    assert vlm_use_rotation_gate_from_config({"use_vlm_rotation_gate": True, "orientation_gate": False}) is True
