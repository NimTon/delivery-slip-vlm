from __future__ import annotations

import numpy as np

from delivery_vlm.preprocess.perspective_rectify import (
    crop_warped_to_expanded_quad_bbox,
    document_rect_dimensions_from_quad,
    order_quad_points,
    rectify_largest_quad_to_rectangle,
    warp_full_image_by_document_homography,
    warp_quad_to_rectangle,
)


def test_order_quad_points_clockwise_input() -> None:
    pts = np.array([[10.0, 20.0], [100.0, 15.0], [95.0, 80.0], [5.0, 75.0]], dtype=np.float32)
    o = order_quad_points(pts)
    assert o.shape == (4, 2)
    # 左上 y 应最小于左下
    assert o[0][1] <= o[3][1] + 1e-3


def test_warp_quad_crop_still_works() -> None:
    img = np.full((100, 200, 3), 240, dtype=np.uint8)
    pts = np.array([[0.0, 0.0], [199.0, 0.0], [199.0, 99.0], [0.0, 99.0]], dtype=np.float32)
    out = warp_quad_to_rectangle(img, pts)
    assert out.shape[0] >= 98 and out.shape[1] >= 198


def test_warp_full_frame_same_quad_as_image_border() -> None:
    """四边形与图像边界一致时，整图透视输出尺寸接近原图（加 pad）。"""
    img = np.full((100, 200, 3), 240, dtype=np.uint8)
    pts = np.array([[0.0, 0.0], [199.0, 0.0], [199.0, 99.0], [0.0, 99.0]], dtype=np.float32)
    dw, dh = document_rect_dimensions_from_quad(pts)
    out, meta = warp_full_image_by_document_homography(img, pts, dst_width=dw, dst_height=dh, pad=2)
    out_w, out_h = meta["out_wh"]
    assert out_w >= 198 and out_h >= 98
    assert out.shape[1] == out_w and out.shape[0] == out_h


def test_rectify_finds_document_quad_synthetic() -> None:
    """白底黑框模拟单据，应能检出四边形并透视拉直。"""
    h, w = 400, 600
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    m = 40
    cv = __import__("cv2", fromlist=["*"])
    cv.rectangle(img, (m, m), (w - m, h - m), (0, 0, 0), 8)
    out, meta = rectify_largest_quad_to_rectangle(
        img,
        min_area_ratio=0.15,
        epsilon_ratios=(0.02, 0.03, 0.05, 0.08),
        max_detect_long_edge=800,
    )
    assert meta.get("applied") is True
    assert meta.get("out_wh") is not None
    assert "crop_xyxy" in meta
    cw, ch = meta["out_wh"]
    assert cw >= 80 and ch >= 80


def test_crop_expand_ratio_widens_bbox() -> None:
    """扩大面积后裁切框应不小于紧贴包围盒（画布足够大时不被边界裁掉）。"""
    warped = np.full((400, 400, 3), 50, dtype=np.uint8)
    quad = np.float32([[120, 130], [280, 125], [275, 270], [118, 268]])
    h = np.eye(3, dtype=np.float64)
    crop0, _m0 = crop_warped_to_expanded_quad_bbox(warped, quad, h, area_expand_ratio=0.0)
    crop1, _m1 = crop_warped_to_expanded_quad_bbox(warped, quad, h, area_expand_ratio=0.2)
    assert crop1.shape[0] * crop1.shape[1] >= crop0.shape[0] * crop0.shape[1]


def test_apply_rotate_skips_legacy_when_perspective_ok() -> None:
    from delivery_vlm.preprocess.geometry import apply_rotate_and_deskew

    h, w = 300, 400
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    cv = __import__("cv2", fromlist=["*"])
    cv.rectangle(img, (30, 30), (w - 30, h - 30), (0, 0, 0), 6)
    out, meta = apply_rotate_and_deskew(
        img,
        deskew={"enabled": True},
        perspective={"enabled": True, "min_area_ratio": 0.12},
    )
    assert meta.get("perspective", {}).get("applied") is True
    assert out.shape[0] > 10

