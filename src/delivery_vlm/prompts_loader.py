from __future__ import annotations

import logging
import sys
from pathlib import Path

from delivery_vlm import prompt_builtins as _fb
from delivery_vlm.config import project_root

_log = logging.getLogger(__name__)


def _candidates(name: str) -> list[Path]:
    root = project_root()
    out: list[Path] = [root / "configs" / "prompts" / name]
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        out.append(Path(sys._MEIPASS) / "configs" / "prompts" / name)  # type: ignore[attr-defined]
    return out


def load_prompt_file(name: str) -> str | None:
    for p in _candidates(name):
        if p.is_file():
            return p.read_text(encoding="utf-8")
    return None


def get_prompt(name: str, default: str) -> str:
    t = load_prompt_file(name)
    if t is not None:
        return t
    _log.debug("未找到外置提示词 %s，使用内置默认。", name)
    return default


def delivery_vlm_system() -> str:
    return get_prompt("vlm_delivery_system.txt", _fb.VLM_DELIVERY_SYSTEM)


def delivery_vlm_user(*, header_keys: list[str], line_keys: list[str]) -> str:
    body = get_prompt("vlm_delivery_user.txt", _fb.VLM_DELIVERY_USER)
    hk = "、".join(header_keys) if header_keys else "（无：请勿输出 header，仅用 lines 或 items）"
    lk = "、".join(line_keys)
    return body.replace("__HEADER_KEYS__", hk).replace("__LINE_KEYS__", lk)
