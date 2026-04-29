"""
颜色 / 明暗预处理（在几何矫正之后、送 VLM 之前使用）。

- ``raw``：原样返回。
- ``shaded``：盒式滤波估计照度后 divide，输出 BGR（与 ``preprocess_image`` 中 tone 分支一致）。
- ``clahe_color``：LAB 的 L 通道做 CLAHE，保留 a/b 颜色信息，适合轻度提亮、压逆光。
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

__all__ = [
    "apply_color_preprocess",
    "clahe_color_bgr",
    "shaded_normalize_bgr",
]


def shaded_normalize_bgr(img_bgr: np.ndarray) -> np.ndarray:
    """照度归一（灰度域）后扩为 3 通道 BGR，利于阴影重的纸张。

    用大核 **盒式滤波** 估计平滑照度场后与原灰度相除，不再使用高斯模糊，以减轻发糊。
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    shade = cv2.blur(gray, (35, 35))
    shade_f = np.maximum(shade.astype(np.float32), 1.0)
    g = gray.astype(np.float32)
    norm = np.clip(g / shade_f * 255.0, 0, 255).astype(np.uint8)
    return cv2.cvtColor(norm, cv2.COLOR_GRAY2BGR)


def clahe_color_bgr(
    img_bgr: np.ndarray,
    *,
    clip_limit: float = 2.0,
    tile_grid_size: int = 8,
) -> np.ndarray:
    """在 LAB 空间对亮度 L 做 CLAHE，合并回彩色 BGR。"""
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    l_ch, a_ch, b_ch = cv2.split(lab)
    tg = max(2, int(tile_grid_size))
    clahe = cv2.createCLAHE(clipLimit=float(clip_limit), tileGridSize=(tg, tg))
    l2 = clahe.apply(l_ch)
    merged = cv2.merge([l2, a_ch, b_ch])
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def apply_color_preprocess(
    img_bgr: np.ndarray,
    mode: str = "clahe_color",
    **kwargs: Any,
) -> np.ndarray:
    """
    ``mode``:
    - ``raw`` / ``none``：不处理；
    - ``shaded``：:func:`shaded_normalize_bgr`；
    - ``clahe_color``：:func:`clahe_color_bgr`（可选 ``clip_limit``、``tile_grid_size``）。
    """
    m = str(mode or "clahe_color").lower().strip()
    if m in ("raw", "none", ""):
        return img_bgr
    if m == "shaded":
        return shaded_normalize_bgr(img_bgr)
    if m == "clahe_color":
        return clahe_color_bgr(
            img_bgr,
            clip_limit=float(kwargs.get("clip_limit", 2.0)),
            tile_grid_size=int(kwargs.get("tile_grid_size", 8)),
        )
    return img_bgr
