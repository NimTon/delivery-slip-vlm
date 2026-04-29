from __future__ import annotations

from delivery_vlm.delivery_schema import (
    attach_trace,
    delivery_columns_from_config,
    parse_delivery_response,
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
