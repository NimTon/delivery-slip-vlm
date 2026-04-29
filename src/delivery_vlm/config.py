from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


def project_root() -> Path:
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def vlm_settings() -> dict[str, str | None]:
    b = (os.getenv("VLM_BASE_URL") or "").strip()
    k = (os.getenv("VLM_API_KEY") or "").strip()
    mm = (os.getenv("VLM_MODEL") or "").strip() or "gpt-4o"
    return {
        "api_key": k or None,
        "base_url": b or None,
        "mm_model": mm,
    }


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    root = project_root()
    load_dotenv(root / ".env")
    if config_path is not None:
        path = config_path
    else:
        path = root / "configs" / "default.yaml"
        if (not path.exists()) and getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
            path = Path(sys._MEIPASS) / "configs" / "default.yaml"  # type: ignore[attr-defined]
    if path.exists() and path.is_dir():
        raise ValueError(f"--config 需要指向 YAML 文件，但你给的是目录: {path}")
    if not path.exists():
        raise FileNotFoundError(f"未找到配置文件: {path}")
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def deep_merge_config(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """递归合并配置：``overrides`` 中与 ``base`` 同名的 dict 会递归合并，否则覆盖。"""
    out: dict[str, Any] = dict(base)
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge_config(out[k], v)  # type: ignore[arg-type]
        else:
            out[k] = v
    return out
