from __future__ import annotations

from delivery_vlm.config import deep_merge_config


def test_deep_merge_nested_dict() -> None:
    base = {
        "preprocess": {"auto_exif": True},
        "vlm": {"use_preprocess": True},
    }
    over = {"preprocess": {"auto_exif": False}}
    m = deep_merge_config(base, over)
    assert m["preprocess"]["auto_exif"] is False
    assert m["vlm"]["use_preprocess"] is True
