"""
基于 PaddleOCR 的四向（0/90/180/270°）选优：对每种旋转跑 OCR，取非空白字符最多的一种作为正向。

需安装：

- ``pip install paddleocr``（以及其运行所需依赖）。

未安装或不可用时不抛错，返回原图与 ``k=0``。
"""

from __future__ import annotations

import re
from typing import Any

import cv2
import numpy as np

from delivery_vlm.preprocess.geometry import rotate_90_bgr

_OCR_CACHE: dict[str, Any] = {}


def ocr_rotate_options_from_config(raw: Any) -> dict[str, Any]:
    """解析 ``preprocess.auto_rotate_ocr``。"""
    if raw is None or raw is False:
        return {"enabled": False}
    if raw is True:
        return {
            "enabled": True,
            "langs": "ch",
            "max_long_edge": 1200,
        }
    if isinstance(raw, dict):
        if not bool(raw.get("enabled", False)):
            return {"enabled": False}
        le = raw.get("max_long_edge", 1200)
        return {
            "enabled": True,
            "langs": str(raw.get("langs", "ch") or "ch").strip(),
            "max_long_edge": int(le) if le is not None else 1200,
        }
    return {"enabled": False}


def _non_ws_len(s: str) -> int:
    return len(re.sub(r"\s+", "", s))


def _map_lang_for_paddle(langs: str) -> str:
    s = (langs or "").lower()
    if "ch" in s or "chi" in s:
        return "ch"
    if "en" in s or "eng" in s:
        return "en"
    return "ch"


def _get_paddle_ocr(lang: str) -> Any:
    if lang in _OCR_CACHE:
        return _OCR_CACHE[lang]
    from paddleocr import PaddleOCR  # type: ignore

    ocr = PaddleOCR(use_textline_orientation=False, lang=lang)
    _OCR_CACHE[lang] = ocr
    return ocr


def _collect_texts_from_paddle_result(rs: Any) -> list[str]:
    texts: list[str] = []
    if rs is None:
        return texts
    if isinstance(rs, dict):
        v = rs.get("rec_texts")
        if isinstance(v, list):
            for t in v:
                if t is not None:
                    s = str(t).strip()
                    if s:
                        texts.append(s)
        return texts
    if isinstance(rs, list):
        for item in rs:
            texts.extend(_collect_texts_from_paddle_result(item))
        if texts:
            return texts
        for line in rs:
            if isinstance(line, (list, tuple)) and len(line) >= 2:
                rec = line[1]
                if isinstance(rec, (list, tuple)) and rec:
                    s = str(rec[0] or "").strip()
                    if s:
                        texts.append(s)
    return texts


def auto_rotate_upright_ocr_bgr(
    img_bgr: np.ndarray,
    *,
    langs: str = "ch",
    max_long_edge: int = 1200,
) -> tuple[np.ndarray, int, dict[str, Any]]:
    """
    对 ``img_bgr`` 的四个 90° 朝向分别做 OCR，取识别文本（去空白）最长的一种；
    返回旋转后的 **全分辨率** 图、顺时针 90° 步数 ``k``、以及各向分数元数据。
    """
    meta: dict[str, Any] = {"scores": {}}
    if img_bgr.ndim != 3 or img_bgr.shape[2] != 3:
        meta["skipped"] = "not_bgr"
        return img_bgr, 0, meta

    try:
        lang = _map_lang_for_paddle(langs)
        ocr = _get_paddle_ocr(lang)
    except ImportError:
        meta["skipped"] = "paddleocr_not_installed"
        return img_bgr, 0, meta
    except Exception as e:  # noqa: BLE001
        meta["skipped"] = f"paddleocr_init_failed:{type(e).__name__}"
        return img_bgr, 0, meta

    h, w = img_bgr.shape[:2]
    work_color = img_bgr
    if max_long_edge > 0:
        long = max(h, w)
        if long > max_long_edge:
            sc = max_long_edge / float(long)
            work_color = cv2.resize(
                img_bgr,
                (int(w * sc), int(h * sc)),
                interpolation=cv2.INTER_AREA,
            )
    best_k = 0
    best_score = -1
    for k in (0, 1, 2, 3):
        g = rotate_90_bgr(work_color, k)
        try:
            rs = ocr.predict(g)
        except Exception as e:  # noqa: BLE001
            meta["scores"][k] = {"error": str(e)}
            continue
        texts = _collect_texts_from_paddle_result(rs)
        score = _non_ws_len("".join(texts))
        meta["scores"][k] = {"chars": score}
        if score > best_score:
            best_score = score
            best_k = k

    if best_score <= 0:
        meta["skipped"] = "no_text_detected"
        return img_bgr, 0, meta

    meta["picked_k"] = best_k
    meta["best_chars"] = best_score
    out = rotate_90_bgr(img_bgr, best_k)
    return out, best_k, meta
