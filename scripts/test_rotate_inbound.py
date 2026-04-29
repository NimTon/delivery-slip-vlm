from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from delivery_vlm.config import project_root
from delivery_vlm.preprocess.geometry import apply_rotate_and_deskew, load_bgr, rotate_90_bgr


def _list_images(root: Path) -> list[Path]:
    exts = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in exts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_dir", type=str, default=r"data\inbound\test")
    ap.add_argument("--out", dest="out_dir", type=str, default=r"data\output\test_rotate")
    args = ap.parse_args()

    in_dir = (project_root() / Path(args.in_dir)).resolve()
    out_dir = (project_root() / Path(args.out_dir)).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    imgs = _list_images(in_dir)
    if not imgs:
        print(f"[warn] no images under: {in_dir}")
        return

    n_ok = 0
    for i, p in enumerate(imgs, start=1):
        try:
            img = load_bgr(p, auto_exif=True)
            out, meta = apply_rotate_and_deskew(
                img,
                perspective={"enabled": True, "min_area_ratio": 0.06},
                auto_rotate_ocr={"enabled": True, "max_long_edge": 1200},
            )
            k = int(meta.get("ocr_auto_rotate_k", 0) or 0)
            ocr_meta = meta.get("ocr_auto_rotate") or {}
            suffix = f"_k{k}"
            if isinstance(ocr_meta, dict) and ocr_meta.get("skipped"):
                suffix += f"_skip-{ocr_meta.get('skipped')}"

            rel = p.relative_to(in_dir)
            dst = (out_dir / rel).with_suffix("")
            dst.parent.mkdir(parents=True, exist_ok=True)
            out_path = dst.parent / f"{dst.name}{suffix}.png"
            ok = cv2.imwrite(str(out_path), out)
            if not ok:
                raise RuntimeError("cv2.imwrite failed")

            # 额外输出：在“方向转正后的原图”上画绿色四边形框，方便肉眼核对检测是否准确
            pmeta = meta.get("perspective") or {}
            quad = None
            if isinstance(pmeta, dict):
                quad = pmeta.get("quad_xy") or pmeta.get("quad_xyxy")
            if isinstance(pmeta, dict) and pmeta.get("applied") and isinstance(pmeta.get("quad_xy"), list):
                try:
                    quad_pts = pmeta["quad_xy"]
                    if isinstance(quad_pts, list) and len(quad_pts) == 4:
                        base = rotate_90_bgr(img, k).copy()
                        pts = (np.array(quad_pts, dtype="float32").reshape(4, 2)).astype("int32").reshape(-1, 1, 2)
                        cv2.polylines(base, [pts], isClosed=True, color=(0, 255, 0), thickness=3)
                        quad_path = dst.parent / f"{dst.name}{suffix}_quad.png"
                        cv2.imwrite(str(quad_path), base)
                except Exception:
                    pass

            n_ok += 1
            print(f"[{i}/{len(imgs)}] {rel} -> {out_path.relative_to(out_dir)}")
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(imgs)}] [error] {p}: {type(e).__name__}: {e}")

    print(f"done: {n_ok}/{len(imgs)} written to {out_dir}")


if __name__ == "__main__":
    main()

