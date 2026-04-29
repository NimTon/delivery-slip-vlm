"""
图像几何前置：文字方向检测转正（PULC）+ 透视矫正。
供 ``preprocess.image.preprocess_image`` 或单独调用。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from delivery_vlm.preprocess.perspective_rectify import (
    perspective_options_from_config,
    rectify_largest_quad_to_rectangle,
)

try:
    from PIL import Image, ImageOps
except Exception:  # noqa: BLE001
    Image = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]


def rotate_90_bgr(img: np.ndarray, k: int) -> np.ndarray:
    """k=0/1/2/3 对应 0°/90°/180°/270°（顺时针 90° 为 1）。"""
    kk = int(k) % 4
    if kk == 0:
        return img
    if kk == 1:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if kk == 2:
        return cv2.rotate(img, cv2.ROTATE_180)
    return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)


def load_bgr(path: Path, *, auto_exif: bool = True) -> np.ndarray:
    """读取为 BGR uint8；优先 EXIF 方向纠正。"""
    img: np.ndarray | None = None
    if auto_exif and Image is not None and ImageOps is not None:
        try:
            with Image.open(path) as im:
                im2 = ImageOps.exif_transpose(im)
                arr = np.array(im2.convert("RGB"))
                img = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        except Exception:  # noqa: BLE001
            img = None
    if img is None:
        img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"无法读取图像: {path}")
    return img


def apply_rotate_and_deskew(
    img_bgr: np.ndarray,
    *,
    perspective: dict[str, Any] | None = None,
    auto_rotate_ocr: dict[str, Any] | bool | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """
    顺序：

    1. **可选** ``auto_rotate_ocr``：文字方向检测转正（PULC，整页 90° 倍数）。
    2. **可选** ``perspective``：在整图中找面积最大的凸四边形，透视矫正为矩形。
    返回 (处理后 BGR, meta：perspective / ocr_auto_rotate)。
    """
    meta: dict[str, Any] = {
        "perspective": None,
        "ocr_auto_rotate_k": None,
        "ocr_auto_rotate": None,
        "text_orientation_method": None,
    }
    img = img_bgr

    from delivery_vlm.preprocess.ocr_rotate import (  # noqa: PLC0415
        auto_rotate_upright_pulc_bgr,
        ocr_rotate_options_from_config,
    )

    ocr_opts = ocr_rotate_options_from_config(auto_rotate_ocr)
    if ocr_opts.get("enabled"):
        meta["text_orientation_method"] = "pulc"
        img, ok, ometa = auto_rotate_upright_pulc_bgr(
            img,
            max_long_edge=int(ocr_opts.get("max_long_edge", 1200) or 0),
        )
        meta["ocr_auto_rotate_k"] = ok
        meta["ocr_auto_rotate"] = ometa

    popts = perspective_options_from_config(perspective)
    if popts.get("enabled"):
        img2, pmeta = rectify_largest_quad_to_rectangle(
            img,
            min_area_ratio=float(popts["min_area_ratio"]),
            epsilon_ratios=tuple(popts["epsilon_ratios"]),
            max_detect_long_edge=int(popts["max_detect_long_edge"]),
            rect_area_expand_ratio=float(popts.get("rect_area_expand_ratio", 0.2)),
        )
        meta["perspective"] = pmeta
        if pmeta.get("applied"):
            img = img2
    return img, meta
