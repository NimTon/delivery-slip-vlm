"""
图像几何前置：可选透视矫正、可选 PaddleOCR 四向 OCR 选优、否则小角度 deskew。
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


def deskew_params_from_config(deskew: dict[str, Any] | bool | None) -> tuple[bool, float, float]:
    """返回 (是否启用, max_abs_degrees, min_abs_degrees)。"""
    if deskew is None or deskew is False:
        return False, 20.0, 0.35
    if deskew is True:
        return True, 20.0, 0.35
    if isinstance(deskew, dict):
        if not bool(deskew.get("enabled", False)):
            return False, 20.0, 0.35
        return (
            True,
            float(deskew.get("max_abs_degrees", 20.0)),
            float(deskew.get("min_abs_degrees", 0.35)),
        )
    return False, 20.0, 0.35


def rotate_bound_bgr(img: np.ndarray, angle_deg: float) -> np.ndarray:
    """绕图像中心旋转任意角度，画布扩展裁满（BGR）。"""
    if abs(angle_deg) < 1e-6:
        return img
    h, w = img.shape[:2]
    center = (w / 2.0, h / 2.0)
    m2d = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    cos = abs(m2d[0, 0])
    sin = abs(m2d[0, 1])
    n_w = int(round(h * sin + w * cos))
    n_h = int(round(h * cos + w * sin))
    m2d[0, 2] += n_w / 2.0 - center[0]
    m2d[1, 2] += n_h / 2.0 - center[1]
    return cv2.warpAffine(
        img,
        m2d,
        (n_w, n_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )


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


def estimate_skew_angle_deg(gray: np.ndarray, *, max_abs_deg: float = 20.0) -> float:
    """
    估计平面内小倾斜角（度），用于纠偏：正值表示需逆时针旋转的角度（与 OpenCV getRotationMatrix2D 一致）。
    基于 HoughLines 检测近似水平线倾斜的中位数。
    """
    h, w = gray.shape[:2]
    if min(h, w) < 48:
        return 0.0
    work = gray
    scale = 1.0
    m = max(h, w)
    if m > 1400:
        scale = 1400.0 / m
        work = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    blur = cv2.GaussianBlur(work, (3, 3), 0)
    edges = cv2.Canny(blur, 50, 150, apertureSize=3)
    min_votes = max(int(min(work.shape) * 0.28), 80)
    lines = cv2.HoughLines(edges, rho=1, theta=np.pi / 180.0, threshold=min_votes)
    if lines is None:
        return 0.0
    candidates: list[float] = []
    for arr in lines[:400]:
        theta = float(arr[0][1])
        deg_theta = float(np.degrees(theta))
        skew = 90.0 - deg_theta
        while skew > 45.0:
            skew -= 180.0
        while skew < -45.0:
            skew += 180.0
        if abs(skew) <= max_abs_deg:
            candidates.append(skew)
    if len(candidates) < 3:
        return 0.0
    return float(np.median(candidates))


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
    deskew: dict[str, Any] | bool | None = None,
    perspective: dict[str, Any] | None = None,
    auto_rotate_ocr: dict[str, Any] | bool | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """
    顺序：

    1. **可选** ``perspective``：在整图中找面积最大的凸四边形，透视矫正为矩形。
    2. **可选** ``auto_rotate_ocr``：PaddleOCR 四向 OCR 选优（整页 90° 倍数）。
    3. 若透视已成功应用，则 **不再** deskew，直接返回。
    4. 否则：可选小角度 deskew。

    返回 (处理后 BGR, meta：perspective / ocr_auto_rotate / deskew_angle_deg)。
    """
    meta: dict[str, Any] = {
        "deskew_angle_deg": None,
        "perspective": None,
        "ocr_auto_rotate_k": None,
        "ocr_auto_rotate": None,
    }
    img = img_bgr

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

    from delivery_vlm.preprocess.ocr_rotate import (  # noqa: PLC0415
        auto_rotate_upright_ocr_bgr,
        ocr_rotate_options_from_config,
    )

    ocr_opts = ocr_rotate_options_from_config(auto_rotate_ocr)
    if ocr_opts.get("enabled"):
        img, ok, ometa = auto_rotate_upright_ocr_bgr(
            img,
            langs=str(ocr_opts.get("langs", "ch")),
            max_long_edge=int(ocr_opts.get("max_long_edge", 1200) or 0),
        )
        meta["ocr_auto_rotate_k"] = ok
        meta["ocr_auto_rotate"] = ometa

    if popts.get("enabled") and meta.get("perspective") and meta["perspective"].get("applied"):
        return img, meta

    on, max_abs, min_abs = deskew_params_from_config(deskew)
    if on:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        ang = estimate_skew_angle_deg(gray, max_abs_deg=max_abs)
        meta["deskew_angle_deg"] = ang
        if abs(ang) >= min_abs:
            img = rotate_bound_bgr(img, ang)
    return img, meta
