from __future__ import annotations

from pathlib import Path

import cv2
import pytest

from delivery_vlm.config import project_root
from delivery_vlm.preprocess.geometry import apply_rotate_and_deskew, load_bgr

_IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def _output_dir() -> Path:
    return project_root() / "data" / "output" / "test_text_orientation"


def _list_test_images() -> list[Path]:
    d = project_root() / "data" / "inbound" / "test"
    if not d.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(d.iterdir()):
        if p.is_file() and p.suffix.lower() in _IMG_EXT:
            out.append(p)
    return out


@pytest.mark.parametrize("path", _list_test_images())
def test_inbound_images_ocr_rotate_smoke(path: Path) -> None:
    """
    对 data/inbound/test 每张图启用文字方向检测转正（PULC），结果写入 data/output/test_text_orientation。
    未安装 PaddleClas 时函数会回退原图，本测试仍应通过。
    """
    img = load_bgr(path, auto_exif=True)
    assert img.ndim == 3 and img.shape[2] == 3

    out, meta = apply_rotate_and_deskew(
        img,
        perspective={"enabled": True, "min_area_ratio": 0.06},
        auto_rotate_ocr={"enabled": True, "max_long_edge": 1200},
    )
    assert out.ndim == 3 and out.shape[2] == 3
    h, w = out.shape[:2]
    assert min(h, w) >= 16

    ocr_meta = meta.get("ocr_auto_rotate") or {}
    picked_k = meta.get("ocr_auto_rotate_k", 0)
    suffix = f"_k{int(picked_k)}"
    if isinstance(ocr_meta, dict) and ocr_meta.get("skipped"):
        suffix += f"_skip-{ocr_meta.get('skipped')}"

    od = project_root() / "data" / "output" / "test_text_orientation"
    od.mkdir(parents=True, exist_ok=True)
    dst = od / f"{path.stem}{suffix}.png"
    assert cv2.imwrite(str(dst), out), f"写入失败: {dst}"


def test_inbound_ocr_rotate_folder_skipped_if_empty() -> None:
    imgs = _list_test_images()
    if imgs:
        pytest.skip("data/inbound/test 有图时由 parametrized 覆盖")
    assert imgs == []
