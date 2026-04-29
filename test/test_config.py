from __future__ import annotations

from delivery_vlm.config import deep_merge_config


def test_deep_merge_nested_dict() -> None:
    base = {
        "preprocess": {"auto_exif": True, "deskew": {"enabled": True, "max_abs_degrees": 20.0}},
        "vlm": {"use_preprocess": True},
    }
    over = {"preprocess": {"deskew": {"enabled": False}}}
    m = deep_merge_config(base, over)
    assert m["preprocess"]["auto_exif"] is True
    assert m["preprocess"]["deskew"]["enabled"] is False
    assert m["preprocess"]["deskew"]["max_abs_degrees"] == 20.0
    assert m["vlm"]["use_preprocess"] is True
