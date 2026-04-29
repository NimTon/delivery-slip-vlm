from __future__ import annotations

import numpy as np

from delivery_vlm.preprocess.geometry import (
    apply_rotate_and_deskew,
    estimate_skew_angle_deg,
    rotate_bound_bgr,
)


def test_estimate_skew_recovers_synthetic_tilt() -> None:
    """水平纹理旋转若干度后，估计角应与旋转角大致相反（容许误差）。"""
    h, w = 480, 640
    img = np.full((h, w), 245, dtype=np.uint8)
    for y in range(40, h, 24):
        img[y : y + 3, :] = 30
    img_bgr = np.stack([img, img, img], axis=-1)
    tilt_deg = 7.5
    tilted = rotate_bound_bgr(img_bgr, tilt_deg)
    gray = tilted[:, :, 1]
    est = estimate_skew_angle_deg(gray, max_abs_deg=20.0)
    assert abs(est + tilt_deg) < 4.0 or abs(est - tilt_deg) < 4.0


def test_apply_rotate_and_deskew_returns_meta() -> None:
    img = np.full((120, 160, 3), 200, dtype=np.uint8)
    out, meta = apply_rotate_and_deskew(
        img,
        deskew={"enabled": False},
    )
    assert out.shape == img.shape
    assert meta.get("deskew_angle_deg") is None


def test_apply_rotate_and_deskew_deskew_disabled_passthrough_shape() -> None:
    img = np.full((200, 300, 3), 220, dtype=np.uint8)
    img[:, :80] = (30, 30, 30)
    out, meta = apply_rotate_and_deskew(
        img,
        deskew={"enabled": False},
    )
    assert out.ndim == 3
    assert out.shape == img.shape
    assert meta.get("deskew_angle_deg") is None

