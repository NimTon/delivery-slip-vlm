from __future__ import annotations

from pathlib import Path

import cv2
import pytest

from delivery_vlm.config import project_root
from delivery_vlm.preprocess.geometry import load_bgr

_IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def _output_dir() -> Path:
    return project_root() / "data" / "output" / "test_exif"


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
def test_inbound_images_exif_transpose_smoke(path: Path) -> None:
    """
    对 data/inbound/test 下每张图：load_bgr(auto_exif=True/False) 各写一张 PNG 到 data/output/test_exif，
    便于对照 EXIF Orientation 是否在 auto_exif 开启时被应用（无 EXIF 时两图通常一致）。
    """
    img_on = load_bgr(path, auto_exif=True)
    img_off = load_bgr(path, auto_exif=False)
    assert img_on.ndim == 3 and img_on.shape[2] == 3
    assert img_off.ndim == 3 and img_off.shape[2] == 3

    od = _output_dir()
    od.mkdir(parents=True, exist_ok=True)
    stem = path.stem
    dst_on = od / f"{stem}_auto_exif.png"
    dst_off = od / f"{stem}_no_exif.png"
    assert cv2.imwrite(str(dst_on), img_on), f"写入失败: {dst_on}"
    assert cv2.imwrite(str(dst_off), img_off), f"写入失败: {dst_off}"


def test_inbound_exif_folder_skipped_if_empty() -> None:
    imgs = _list_test_images()
    if imgs:
        pytest.skip("data/inbound/test 有图时由 parametrized 覆盖")
    assert imgs == []
