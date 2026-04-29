"""
检测图像中面积最大的凸四边形（透视下常为梯形），估计「单据应占的」轴对齐矩形宽高，
再用同一单应性变换对**整张原图**做 ``warpPerspective``（扩展画布以包住变换后的四角），
而不是只裁出单据小图。
失败时由调用方决定是否回退到 :mod:`geometry` 的 deskew。
"""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np


def order_quad_points(pts: np.ndarray) -> np.ndarray:
    """四顶点排序为 [左上, 右上, 右下, 左下]，形状 (4, 2) float32。"""
    pts = np.asarray(pts, dtype=np.float32).reshape(-1, 2)
    if pts.shape[0] != 4:
        raise ValueError("需要恰好 4 个点")
    x_sorted = pts[np.argsort(pts[:, 0]), :]
    left = x_sorted[:2, :]
    right = x_sorted[2:, :]
    left = left[np.argsort(left[:, 1]), :]
    right = right[np.argsort(right[:, 1]), :]
    tl, bl = left
    tr, br = right
    return np.array([tl, tr, br, bl], dtype=np.float32)


def document_rect_dimensions_from_quad(quad_xy: np.ndarray) -> tuple[int, int]:
    """由四边形边长估算单据矫正后的轴对齐矩形宽高 (w, h)，至少为 2。"""
    rect = order_quad_points(quad_xy)
    tl, tr, br, bl = rect
    wa = float(np.linalg.norm(br - bl))
    wb = float(np.linalg.norm(tr - tl))
    max_w = max(int(round(wa)), int(round(wb)))
    ha = float(np.linalg.norm(tr - br))
    hb = float(np.linalg.norm(tl - bl))
    max_h = max(int(round(ha)), int(round(hb)))
    return max(max_w, 2), max(max_h, 2)


def warp_quad_to_rectangle(img_bgr: np.ndarray, quad_xy: np.ndarray) -> np.ndarray:
    """仅将四边形区域透视贴到矩形画布（裁切式）。整图矫正请用 :func:`warp_full_image_by_document_homography`。"""
    rect = order_quad_points(quad_xy)
    max_w, max_h = document_rect_dimensions_from_quad(quad_xy)
    dst = np.array(
        [[0, 0], [max_w - 1, 0], [max_w - 1, max_h - 1], [0, max_h - 1]],
        dtype=np.float32,
    )
    m = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(
        img_bgr,
        m,
        (max_w, max_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )


def warp_full_image_by_document_homography(
    img_bgr: np.ndarray,
    src_quad_xy: np.ndarray,
    *,
    dst_width: int,
    dst_height: int,
    pad: int = 2,
) -> tuple[np.ndarray, dict[str, Any]]:
    """
    用 ``getPerspectiveTransform(单据四角 → 轴对齐矩形)`` 的同一矩阵，对**整幅** ``img_bgr`` 透视变换；
    输出尺寸为变换后原图四角包围盒（加 ``pad``），单据四边形在输出中落在 ``(0,0)-(dst_w-1,dst_h-1)`` 对应矩形处。
    """
    rect = order_quad_points(src_quad_xy)
    dst = np.array(
        [
            [0.0, 0.0],
            [float(dst_width - 1), 0.0],
            [float(dst_width - 1), float(dst_height - 1)],
            [0.0, float(dst_height - 1)],
        ],
        dtype=np.float32,
    )
    m = cv2.getPerspectiveTransform(rect, dst)
    h0, w0 = img_bgr.shape[:2]
    corners = np.array(
        [
            [[0.0, 0.0]],
            [[float(w0 - 1), 0.0]],
            [[float(w0 - 1), float(h0 - 1)]],
            [[0.0, float(h0 - 1)]],
        ],
        dtype=np.float32,
    )
    mapped = cv2.perspectiveTransform(corners, m).reshape(-1, 2)
    xmin = float(np.floor(np.min(mapped[:, 0]))) - float(pad)
    ymin = float(np.floor(np.min(mapped[:, 1]))) - float(pad)
    xmax = float(np.ceil(np.max(mapped[:, 0]))) + float(pad)
    ymax = float(np.ceil(np.max(mapped[:, 1]))) + float(pad)
    out_w = max(2, int(xmax - xmin))
    out_h = max(2, int(ymax - ymin))
    t = np.array([[1.0, 0.0, -xmin], [0.0, 1.0, -ymin], [0.0, 0.0, 1.0]], dtype=np.float64)
    m2 = (t @ m).astype(np.float64)
    out = cv2.warpPerspective(
        img_bgr,
        m2,
        (out_w, out_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    wmeta: dict[str, Any] = {
        "out_wh": (out_w, out_h),
        "dst_doc_wh": (dst_width, dst_height),
        "bbox_xyxy": (xmin, ymin, xmax, ymax),
        "H": m2.astype(np.float64).tolist(),
    }
    return out, wmeta


def crop_warped_to_expanded_quad_bbox(
    warped_bgr: np.ndarray,
    src_quad_xy: np.ndarray,
    homography_m2: np.ndarray,
    *,
    area_expand_ratio: float = 0.0,
) -> tuple[np.ndarray, dict[str, Any]]:
    """
    将原图四边形经 ``homography_m2`` 映射到 warped 后的位置，取轴对齐包围盒；
    面积按 ``(1 + area_expand_ratio)`` 以中心同比放大（宽高乘 ``sqrt(1+ratio)``），再裁切到图像范围内。
    ``area_expand_ratio <= 0`` 时仅裁紧贴包围盒（数值误差可略扩 1px）。
    """
    h, w = warped_bgr.shape[:2]
    rect = order_quad_points(np.asarray(src_quad_xy, dtype=np.float32))
    pts = rect.reshape(1, 4, 2).astype(np.float32)
    h32 = np.asarray(homography_m2, dtype=np.float32)
    mapped = cv2.perspectiveTransform(pts, h32).reshape(-1, 2)
    x_min = float(np.min(mapped[:, 0]))
    x_max = float(np.max(mapped[:, 0]))
    y_min = float(np.min(mapped[:, 1]))
    y_max = float(np.max(mapped[:, 1]))
    bw = max(x_max - x_min, 1.0)
    bh = max(y_max - y_min, 1.0)
    cx = (x_min + x_max) * 0.5
    cy = (y_min + y_max) * 0.5
    scale = math.sqrt(max(0.0, 1.0 + float(area_expand_ratio)))
    nw = bw * scale
    nh = bh * scale
    nx0 = int(math.floor(cx - nw * 0.5))
    ny0 = int(math.floor(cy - nh * 0.5))
    nx1 = int(math.ceil(cx + nw * 0.5))
    ny1 = int(math.ceil(cy + nh * 0.5))
    nx0 = max(0, nx0)
    ny0 = max(0, ny0)
    nx1 = min(w, nx1)
    ny1 = min(h, ny1)
    cmeta: dict[str, Any] = {
        "crop_xyxy": (nx0, ny0, nx1, ny1),
        "tight_xyxy": (
            max(0, int(math.floor(x_min))),
            max(0, int(math.floor(y_min))),
            min(w, int(math.ceil(x_max))),
            min(h, int(math.ceil(y_max))),
        ),
        "area_expand_ratio": float(area_expand_ratio),
    }
    if nx1 <= nx0 or ny1 <= ny0:
        cmeta["skipped"] = True
        return warped_bgr, cmeta
    crop = warped_bgr[ny0:ny1, nx0:nx1].copy()
    return crop, cmeta


def _scale_points_back(pts: np.ndarray, sx: float, sy: float) -> np.ndarray:
    out = pts.astype(np.float64).copy()
    out[:, 0] *= sx
    out[:, 1] *= sy
    return out.astype(np.float32)


def _find_quad_on_gray(
    gray_small: np.ndarray,
    *,
    min_area_ratio: float,
    epsilon_ratios: tuple[float, ...],
) -> np.ndarray | None:
    h, w = gray_small.shape[:2]
    area_img = float(h * w)
    blurred = cv2.GaussianBlur(gray_small, (5, 5), 0)
    edged = cv2.Canny(blurred, 40, 120)
    edged = cv2.dilate(edged, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=2)

    cnts, _ = cv2.findContours(edged, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cnts = sorted(cnts, key=cv2.contourArea, reverse=True)[:40]

    def try_contours(contours: list[np.ndarray]) -> np.ndarray | None:
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area_ratio * area_img:
                continue
            peri = cv2.arcLength(cnt, True)
            if peri < 1e-6:
                continue
            for er in epsilon_ratios:
                approx = cv2.approxPolyDP(cnt, er * peri, True)
                if len(approx) == 4 and cv2.isContourConvex(approx):
                    return approx.reshape(4, 2).astype(np.float32)
        return None

    q = try_contours(cnts)
    if q is not None:
        return q

    # 备选：自适应二值 + 轮廓（适合边缘较弱的手写纸张）
    th = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 25, 11
    )
    th = cv2.medianBlur(th, 5)
    cnts2, _ = cv2.findContours(th, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cnts2 = sorted(cnts2, key=cv2.contourArea, reverse=True)[:40]
    return try_contours(cnts2)


def rectify_largest_quad_to_rectangle(
    img_bgr: np.ndarray,
    *,
    min_area_ratio: float = 0.08,
    epsilon_ratios: tuple[float, ...] = (0.02, 0.03, 0.045, 0.06),
    max_detect_long_edge: int = 1200,
    rect_area_expand_ratio: float = 0.2,
) -> tuple[np.ndarray, dict[str, Any]]:
    """
    在缩小图上找最大凸四边形，顶点映射回原图尺寸后，对**整张原图**做透视矫正，
    再按单据在输出中的包围盒将面积扩大 ``(1 + rect_area_expand_ratio)`` 后**裁切**。

    返回 ``(图像, meta)``；meta 含 ``applied``、``out_wh``（裁切后）、``crop_*``、``dst_doc_wh`` 等。
    """
    meta: dict[str, Any] = {"applied": False, "reason": None}
    h0, w0 = img_bgr.shape[:2]
    long0 = max(h0, w0)
    scale = 1.0
    if long0 > max_detect_long_edge > 0:
        scale = max_detect_long_edge / float(long0)
    w1 = max(8, int(round(w0 * scale)))
    h1 = max(8, int(round(h0 * scale)))
    small = cv2.resize(img_bgr, (w1, h1), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

    quad = _find_quad_on_gray(
        gray,
        min_area_ratio=min_area_ratio,
        epsilon_ratios=epsilon_ratios,
    )
    if quad is None:
        meta["reason"] = "no_quad_found"
        return img_bgr, meta

    sx = w0 / float(w1)
    sy = h0 / float(h1)
    quad_full = _scale_points_back(quad, sx, sy)
    area_q = float(cv2.contourArea(quad_full.reshape(-1, 1, 2)))
    meta["quad_area_ratio"] = area_q / float(w0 * h0)
    meta["quad_xy"] = quad_full.tolist()

    dst_w, dst_h = document_rect_dimensions_from_quad(quad_full)
    warped, wmeta = warp_full_image_by_document_homography(
        img_bgr, quad_full, dst_width=dst_w, dst_height=dst_h, pad=2
    )
    meta.update({k: v for k, v in wmeta.items() if k != "H"})
    h_list = wmeta.get("H")
    m2 = np.asarray(h_list, dtype=np.float64)
    cropped, cmeta = crop_warped_to_expanded_quad_bbox(
        warped,
        quad_full,
        m2,
        area_expand_ratio=float(rect_area_expand_ratio),
    )
    meta["pre_crop_out_wh"] = wmeta.get("out_wh")
    meta.update(cmeta)
    ch, cw = cropped.shape[:2]
    meta["out_wh"] = (cw, ch)
    meta["applied"] = True
    meta["reason"] = "perspective_ok"
    return cropped, meta


def perspective_options_from_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    """解析 ``configs.default.yaml`` 中 ``preprocess.perspective``。"""
    if not raw or not isinstance(raw, dict):
        return {"enabled": False}
    if not bool(raw.get("enabled", False)):
        return {"enabled": False}
    eps = raw.get("approx_epsilon_ratios")
    if isinstance(eps, list) and eps:
        er = tuple(float(x) for x in eps)
    else:
        er = (0.02, 0.03, 0.045, 0.06)
    return {
        "enabled": True,
        "min_area_ratio": float(raw.get("min_area_ratio", 0.08)),
        "epsilon_ratios": er,
        "max_detect_long_edge": int(raw.get("max_detect_long_edge", 1200)),
        "rect_area_expand_ratio": float(raw.get("rect_area_expand_ratio", 0.2)),
    }
