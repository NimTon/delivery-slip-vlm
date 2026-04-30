from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Iterable


def list_input_images(input_dir: Path) -> list[Path]:
    exts = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
    out: list[Path] = []
    for p in sorted(input_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() in exts:
            out.append(p)
    return sorted(out)


def rename_images_sequentially(
    images: Iterable[Path],
    *,
    digits: int = 3,
) -> list[Path]:
    """
    将输入图片按给定顺序就地重命名为 ``{id:0Nd}{suffix}``（例如 ``000.jpg``）。

    - 两阶段重命名（先改为临时名再改为目标名），避免同目录内互相覆盖/冲突。
    - 后缀名取原文件的 suffix（统一小写）。
    """
    imgs = [p for p in images]
    if not imgs:
        return []

    final_map: dict[Path, Path] = {}
    for i, p in enumerate(imgs):
        suf = p.suffix.lower()
        final_map[p] = p.with_name(f"{i:0{digits}d}{suf}")

    # 若全部已是目标名则直接返回
    try:
        if all(p.resolve() == final_map[p].resolve() for p in imgs):
            return [final_map[p] for p in imgs]
    except OSError:
        pass

    # 第一阶段：临时名（防冲突）
    tmp_map: dict[Path, Path] = {}
    for p in imgs:
        if not p.exists():
            tmp_map[p] = p
            continue
        tmp = p.with_name(f".__tmp__{uuid.uuid4().hex}__{p.name}")
        tmp_map[p] = tmp
        p.rename(tmp)

    # 第二阶段：目标名
    out: list[Path] = []
    for p in imgs:
        tmp = tmp_map[p]
        dst = final_map[p]
        if tmp == dst:
            out.append(dst)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp.rename(dst)
        out.append(dst)
    return out


def page_id_for(path: Path, root: Path | None = None) -> str:
    stem: str
    if root is not None:
        try:
            rel = path.resolve().relative_to(root.resolve())
            stem = rel.with_suffix("").as_posix().replace("/", "__").replace("\\", "__")
        except ValueError:
            stem = path.stem
    else:
        stem = path.stem
    safe = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", stem)
    return safe[:120] or uuid.uuid4().hex[:12]
