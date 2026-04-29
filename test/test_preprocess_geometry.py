from __future__ import annotations

import numpy as np

from delivery_vlm.preprocess.geometry import apply_rotate_and_deskew


def test_apply_rotate_and_deskew_returns_meta() -> None:
    img = np.full((120, 160, 3), 200, dtype=np.uint8)
    out, meta = apply_rotate_and_deskew(img)
    assert out.shape == img.shape


def test_apply_rotate_and_deskew_passthrough_shape() -> None:
    img = np.full((200, 300, 3), 220, dtype=np.uint8)
    img[:, :80] = (30, 30, 30)
    out, meta = apply_rotate_and_deskew(img)
    assert out.ndim == 3
    assert out.shape == img.shape
    assert "perspective" in meta

