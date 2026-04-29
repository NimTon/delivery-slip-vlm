from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from delivery_vlm.preprocess.geometry import load_bgr, rotate_90_bgr
from delivery_vlm.preprocess.ocr_rotate import auto_rotate_upright_pulc_bgr


def _mk_demo_image(path: Path) -> None:
    img = np.full((420, 860, 3), 255, dtype=np.uint8)
    cv2.putText(img, "NO. 12345", (40, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (0, 0, 0), 3)
    cv2.putText(img, "Shipped Qty: 18", (40, 210), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 2)
    cv2.putText(img, "2026-04-29", (40, 300), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 3)
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("encode demo png failed")
    path.parent.mkdir(parents=True, exist_ok=True)
    buf.tofile(str(path))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", type=str, default="", help="待测试图片路径；不传则自动生成 demo 图")
    ap.add_argument("--rotate-k", type=int, default=1, help="先人为顺时针旋转 90°k，用于测试方向检测")
    ap.add_argument("--method", type=str, default="pulc", choices=["pulc"], help="方向检测方法")
    args = ap.parse_args()

    if args.image:
        p = Path(args.image)
    else:
        p = Path("data/out/_demo_orientation/demo.png")
        _mk_demo_image(p)

    img = load_bgr(p, auto_exif=False)
    img = rotate_90_bgr(img, int(args.rotate_k))

    out, k, meta = auto_rotate_upright_pulc_bgr(img, max_long_edge=1200)

    out_p = Path("data/out/_demo_orientation/out.png")
    out_p.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", out)
    if ok:
        buf.tofile(str(out_p))

    print(f"method={args.method} predicted_k={k} out={out_p}")
    print(meta)


if __name__ == "__main__":
    main()

