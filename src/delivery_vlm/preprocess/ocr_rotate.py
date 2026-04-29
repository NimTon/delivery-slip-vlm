"""
文字方向检测（0/90/180/270°）并转正。

当前实现使用 PaddleClas PULC 的 ``text_image_orientation``（更快，专注方向而非识别内容）：

- 配置 ``preprocess.auto_rotate_ocr.method: pulc`` 启用
- 需安装：``pip install paddleclas``（以及其运行所需依赖）
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from delivery_vlm.preprocess.geometry import rotate_90_bgr
from delivery_vlm.config import project_root

_PULC_CACHE: dict[str, Any] = {}


def ocr_rotate_options_from_config(raw: Any) -> dict[str, Any]:
    """解析 ``preprocess.auto_rotate_ocr``（历史名称保留；现仅支持 PULC 方向检测）。"""
    if raw is None or raw is False:
        return {"enabled": False}
    if raw is True:
        return {
            "enabled": True,
            "max_long_edge": 1200,
        }
    if isinstance(raw, dict):
        if not bool(raw.get("enabled", False)):
            return {"enabled": False}
        le = raw.get("max_long_edge", 1200)
        return {
            "enabled": True,
            "max_long_edge": int(le) if le is not None else 1200,
        }
    return {"enabled": False}


def _get_pulc_text_orientation() -> Any:
    """
    PaddleClas PULC：text_image_orientation（0/90/180/270）分类器。
    以缓存方式避免重复初始化与重复下载权重。
    """
    key = "text_image_orientation"
    if key in _PULC_CACHE:
        return _PULC_CACHE[key]
    from paddleclas import PaddleClas  # type: ignore

    cls = PaddleClas(model_name="text_image_orientation")
    _PULC_CACHE[key] = cls
    return cls


class _PulcLegacyPredictor:
    """
    PaddlePaddle 3.x 默认推理可能要求 PIR 格式（inference.json），但 PaddleClas PULC
    仍会下载旧格式（inference.pdmodel/inference.pdiparams）。此类用旧格式显式加载，
    作为 Windows 环境下的兼容兜底。
    """

    def __init__(self, model_dir: str):
        from paddle.inference import Config, create_predictor  # type: ignore

        model_file = str(Path(model_dir) / "inference.pdmodel")
        params_file = str(Path(model_dir) / "inference.pdiparams")
        if not Path(model_file).is_file() or not Path(params_file).is_file():
            raise FileNotFoundError(f"missing model files in {model_dir}")

        cfg = Config(model_file, params_file)
        cfg.disable_gpu()
        cfg.disable_glog_info()
        # 旧格式模型在部分 PaddlePaddle 版本 + oneDNN 下可能触发 fused_conv2d 报错，
        # 这里优先保证可用性：关闭 IR 融合，并尽量禁用 MKLDNN/oneDNN。
        cfg.switch_ir_optim(False)
        if hasattr(cfg, "disable_mkldnn"):
            try:
                cfg.disable_mkldnn()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass
        cfg.enable_memory_optim()
        cfg.switch_use_feed_fetch_ops(False)
        self.predictor = create_predictor(cfg)
        in_name = self.predictor.get_input_names()[0]
        out_name = self.predictor.get_output_names()[0]
        self.in_handle = self.predictor.get_input_handle(in_name)
        self.out_handle = self.predictor.get_output_handle(out_name)

    @staticmethod
    def _preprocess(img_bgr: np.ndarray) -> np.ndarray:
        """
        参考 PaddleClas 常见分类预处理：
        BGR → RGB，Resize(256) → CenterCrop(224) → Normalize → CHW，float32。
        """
        rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        if min(h, w) <= 0:
            raise ValueError("bad image")
        # resize short side to 256
        short = min(h, w)
        scale = 256.0 / float(short)
        nh, nw = int(round(h * scale)), int(round(w * scale))
        rgb = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_LINEAR)
        # center crop 224
        ch, cw = 224, 224
        y0 = max((nh - ch) // 2, 0)
        x0 = max((nw - cw) // 2, 0)
        rgb = rgb[y0 : y0 + ch, x0 : x0 + cw]
        if rgb.shape[0] != ch or rgb.shape[1] != cw:
            rgb = cv2.resize(rgb, (cw, ch), interpolation=cv2.INTER_LINEAR)
        x = rgb.astype("float32") / 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype="float32")
        std = np.array([0.229, 0.224, 0.225], dtype="float32")
        x = (x - mean) / std
        x = np.transpose(x, (2, 0, 1))  # CHW
        x = np.expand_dims(x, 0)  # NCHW
        return x

    def predict_k(self, img_bgr: np.ndarray) -> tuple[int, dict[str, Any]]:
        x = self._preprocess(img_bgr)
        self.in_handle.copy_from_cpu(x)
        self.predictor.run()
        out = self.out_handle.copy_to_cpu()
        out = np.asarray(out)
        if out.ndim == 2 and out.shape[0] == 1:
            logits = out[0]
        else:
            logits = out.reshape(-1)
        idx = int(np.argmax(logits))
        # 约定 0/1/2/3 → 当前朝向为 0/90/180/270（顺时针 90° 为 1）
        pred_k = idx % 4
        meta: dict[str, Any] = {"legacy": True, "class_id": idx, "pred_k": pred_k}
        return pred_k, meta


def _resolve_text_image_orientation_model_dir() -> Path:
    """
    优先使用项目内置模型目录：

    - <project_root>/models/text_image_orientation/

    若不存在则回退到 PaddleClas 默认缓存目录：

    - ~/.paddleclas/inference_model/PULC/text_image_orientation/
    """
    p0 = (project_root() / "models" / "text_image_orientation").resolve()
    if (p0 / "inference.pdmodel").is_file() and (p0 / "inference.pdiparams").is_file():
        return p0
    return (Path.home() / ".paddleclas" / "inference_model" / "PULC" / "text_image_orientation").resolve()


def _get_pulc_legacy_predictor() -> _PulcLegacyPredictor:
    key = "pulc_legacy_text_image_orientation"
    cached = _PULC_CACHE.get(key)
    if cached is not None:
        return cached
    model_dir = _resolve_text_image_orientation_model_dir()
    pred = _PulcLegacyPredictor(str(model_dir))
    _PULC_CACHE[key] = pred
    return pred


def _parse_pulc_orientation_to_k(raw: Any) -> tuple[int, dict[str, Any]]:
    """
    尽量兼容 PaddleClas 返回结构：
    - 可能是 list[dict] / dict / generator
    - label 可能是 0/90/180/270，也可能是 0/1/2/3（映射为 0/90/180/270）
    """
    meta: dict[str, Any] = {"raw": raw}

    item: Any = raw
    try:
        if hasattr(raw, "__iter__") and not isinstance(raw, (dict, list, tuple, str, bytes)):
            # generator → first
            item = next(iter(raw), None)
    except Exception:  # noqa: BLE001
        item = raw

    if isinstance(item, list) and item:
        item = item[0]

    if not isinstance(item, dict):
        meta["skipped"] = "pulc_unexpected_result"
        return 0, meta

    # PaddleClas 常见字段：label_name / class_name / label / category_id / score
    label = item.get("label_name") or item.get("class_name") or item.get("label") or item.get("category_id")
    score = item.get("score") or item.get("scores") or item.get("prob") or item.get("confidence")
    meta["label"] = label
    meta["score"] = score

    def _to_int(x: Any) -> int | None:
        try:
            if x is None:
                return None
            if isinstance(x, (int, float)):
                return int(x)
            s = str(x).strip()
            m = re.search(r"-?\d+", s)
            return int(m.group(0)) if m else None
        except Exception:  # noqa: BLE001
            return None

    v = _to_int(label)
    if v is None:
        meta["skipped"] = "pulc_no_label"
        return 0, meta

    if v in (0, 90, 180, 270):
        deg = v
    elif v in (0, 1, 2, 3):
        deg = (v % 4) * 90
    else:
        # 有些实现会直接输出角度索引或其他编码，兜底取四象限
        deg = (v % 4) * 90

    k = (deg // 90) % 4
    meta["deg"] = deg
    meta["k"] = k
    return k, meta


def auto_rotate_upright_pulc_bgr(
    img_bgr: np.ndarray,
    *,
    max_long_edge: int = 1200,
) -> tuple[np.ndarray, int, dict[str, Any]]:
    """
    使用 PaddleClas PULC 的 ``text_image_orientation`` 预测整页方向（0/90/180/270），并旋转为正向。
    返回旋转后的 **全分辨率** 图、顺时针 90° 步数 ``k``、以及预测元数据。
    """
    meta: dict[str, Any] = {}
    if img_bgr.ndim != 3 or img_bgr.shape[2] != 3:
        meta["skipped"] = "not_bgr"
        return img_bgr, 0, meta

    legacy: _PulcLegacyPredictor | None = None
    try:
        legacy = _get_pulc_legacy_predictor()
    except ImportError:
        meta["skipped"] = "paddlepaddle_not_installed"
        return img_bgr, 0, meta
    except Exception as e:  # noqa: BLE001
        meta["skipped"] = "pulc_model_load_failed"
        meta["model_dir"] = str(_resolve_text_image_orientation_model_dir())
        meta["error"] = f"{type(e).__name__}: {e}"
        return img_bgr, 0, meta

    h, w = img_bgr.shape[:2]
    work = img_bgr
    if max_long_edge > 0:
        long = max(h, w)
        if long > max_long_edge:
            sc = max_long_edge / float(long)
            work = cv2.resize(img_bgr, (int(w * sc), int(h * sc)), interpolation=cv2.INTER_AREA)

    # PaddleClas 对输入类型的兼容性在不同版本间可能有差异；优先传 ndarray，失败再走临时文件。
    try:
        pred_k, lmeta = legacy.predict_k(work)
    except Exception as e:  # noqa: BLE001
        meta["skipped"] = "pulc_predict_failed"
        meta["error"] = f"{type(e).__name__}: {e}"
        return img_bgr, 0, meta
    meta["pulc"] = lmeta
    meta["model_dir"] = str(_resolve_text_image_orientation_model_dir())

    # pred_k 表示“当前图像的 90°朝向”，要转正则应用其反向旋转
    apply_k = (-int(pred_k)) % 4
    # 业务约束：不允许 180° 转正（k=2）
    if apply_k == 2:
        meta["pulc_180_blocked"] = True
        meta["pulc_apply_k_raw"] = 2
        apply_k = 0
    meta["pulc_apply_k"] = apply_k
    out = rotate_90_bgr(img_bgr, apply_k)
    return out, apply_k, meta
