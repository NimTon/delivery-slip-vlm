from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from delivery_vlm.config import project_root
from delivery_vlm.preprocess.color_tone import apply_color_preprocess
from delivery_vlm.preprocess.geometry import apply_rotate_and_deskew, load_bgr

_IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def _output_color_dir() -> Path:
    return project_root() / "data" / "output" / "test_color"


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


def test_apply_color_preprocess_synthetic_smoke() -> None:
    """无 inbound 图时仍可通过：小图跑 clahe / shaded / raw。"""
    rng = np.random.default_rng(0)
    img = (rng.random((64, 80, 3)) * 200 + 20).astype(np.uint8)
    raw = apply_color_preprocess(img, "raw")
    assert raw.shape == img.shape and np.array_equal(raw, img)
    cla = apply_color_preprocess(img, "clahe_color")
    assert cla.ndim == 3 and cla.shape[2] == 3
    sh = apply_color_preprocess(img, "shaded")
    assert sh.ndim == 3 and sh.shape[2] == 3


@pytest.mark.parametrize("path", _list_test_images())
def test_inbound_images_color_preprocess_smoke(path: Path) -> None:
    """
    对 data/inbound/test 每张图：几何前置（与几何测试一致）→ 颜色预处理（CLAHE + shaded 对照）；
    写入 data/output/test_color。
    """
    img = load_bgr(path, auto_exif=True)
    assert img.ndim == 3 and img.shape[2] == 3
    geo, _meta = apply_rotate_and_deskew(
        img,
        deskew={"enabled": True, "max_abs_degrees": 20.0, "min_abs_degrees": 0.35},
        perspective={"enabled": True, "min_area_ratio": 0.06},
    )
    assert geo.ndim == 3
    h, w = geo.shape[:2]
    assert min(h, w) >= 16

    cla = apply_color_preprocess(geo, "clahe_color")
    shaded = apply_color_preprocess(geo, "shaded")
    assert cla.shape == geo.shape
    assert shaded.shape == geo.shape

    od = _output_color_dir()
    od.mkdir(parents=True, exist_ok=True)
    stem = path.stem
    dst_cla = od / f"{stem}_clahe.png"
    dst_sh = od / f"{stem}_shaded.png"
    assert cv2.imwrite(str(dst_cla), cla), f"写入失败: {dst_cla}"
    assert cv2.imwrite(str(dst_sh), shaded), f"写入失败: {dst_sh}"

    reread = cv2.imread(str(dst_cla))
    assert reread is not None and reread.shape[:2] == (h, w)


def test_inbound_color_folder_skipped_if_empty() -> None:
    imgs = _list_test_images()
    if imgs:
        pytest.skip("data/inbound/test 有图时由 parametrized 覆盖")
    assert imgs == []
