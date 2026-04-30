from __future__ import annotations

from pathlib import Path

from delivery_vlm.pipeline.scan_pages import rename_images_sequentially


def test_rename_images_sequentially_keeps_order(tmp_path: Path) -> None:
    p1 = tmp_path / "b.jpg"
    p2 = tmp_path / "a.jpg"
    p3 = tmp_path / "001-x.jpg"
    for p in (p1, p2, p3):
        p.write_bytes(b"x")

    out = rename_images_sequentially([p1, p2, p3], digits=3)
    assert [p.name for p in out] == ["000.jpg", "001.jpg", "002.jpg"]
    assert all(p.is_file() for p in out)

