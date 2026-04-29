from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from delivery_vlm.preprocess.color_tone import shaded_normalize_bgr
from delivery_vlm.preprocess.geometry import apply_rotate_and_deskew, load_bgr

__all__ = ["preprocess_image"]


def preprocess_image(
    src: Path,
    dst: Path,
    max_long_edge: int = 2000,
    tone_mode: str = "shaded",
    auto_exif: bool = True,
    perspective: dict[str, Any] | None = None,
    auto_rotate_ocr: dict[str, Any] | bool | None = None,
) -> Path:
    """
    读图 → :mod:`geometry`（文字方向检测转正（PULC）→ 透视）→ 可选缩放 → 可选阴影压制 → 写 PNG。

    ``max_long_edge``:
    - 正数：长边超过该值时等比缩小；
    - 0 或负数：不缩小。

    ``tone_mode``: ``raw`` 保留彩色；``shaded`` 做照度归一（默认）。
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    img = load_bgr(src, auto_exif=auto_exif)
    img, _meta = apply_rotate_and_deskew(
        img,
        perspective=perspective,
        auto_rotate_ocr=auto_rotate_ocr,
    )

    h, w = img.shape[:2]
    long = max(h, w)
    if max_long_edge > 0 and long > max_long_edge:
        scale = max_long_edge / float(long)
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    mode = str(tone_mode or "shaded").lower().strip()
    if mode == "raw":
        out = img
    else:
        out = shaded_normalize_bgr(img)
    ok, buf = cv2.imencode(".png", out)
    if not ok:
        raise RuntimeError("PNG 编码失败")
    buf.tofile(str(dst))
    return dst
