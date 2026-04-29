from __future__ import annotations

from pathlib import Path

import cv2
import pytest

from delivery_vlm.config import project_root
from delivery_vlm.preprocess.geometry import apply_rotate_and_deskew, load_bgr

_IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def _output_dir() -> Path:
    return project_root() / "data" / "output" / "test"


def _list_test_images() -> list[Path]:
    root = project_root()
    d = root / "data" / "inbound" / "test"
    if not d.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(d.iterdir()):
        if p.is_file() and p.suffix.lower() in _IMG_EXT:
            out.append(p)
    return out


@pytest.mark.parametrize("path", _list_test_images())
def test_inbound_images_geometry_smoke(path: Path) -> None:
    """对 data/inbound/test 下每张图跑几何前置，断言尺寸；结果写入 data/output/test。"""
    img = load_bgr(path, auto_exif=True)
    assert img.ndim == 3 and img.shape[2] == 3
    out, meta = apply_rotate_and_deskew(
        img,
        perspective={"enabled": True, "min_area_ratio": 0.06},
    )
    assert out.ndim == 3
    h, w = out.shape[:2]
    assert min(h, w) >= 16

    od = _output_dir()
    od.mkdir(parents=True, exist_ok=True)
    dst = od / f"{path.stem}_geometry.png"
    assert cv2.imwrite(str(dst), out), f"写入失败: {dst}"


def test_inbound_folder_skipped_if_empty() -> None:
    imgs = _list_test_images()
    if imgs:
        pytest.skip("data/inbound/test 有图时由 parametrized 覆盖")
    assert imgs == []
