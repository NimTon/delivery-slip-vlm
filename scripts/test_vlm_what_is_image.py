from __future__ import annotations

import argparse
import os
import random
from pathlib import Path

from dotenv import load_dotenv

from delivery_vlm.config import project_root, vlm_settings
from delivery_vlm.llm.client import OpenAICompatClient


def _list_images(d: Path) -> list[Path]:
    exts = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
    if not d.is_dir():
        return []
    return sorted(p for p in d.rglob("*") if p.is_file() and p.suffix.lower() in exts)


def _guess_content_type(p: Path) -> str:
    s = p.suffix.lower()
    if s == ".png":
        return "image/png"
    if s in (".jpg", ".jpeg"):
        return "image/jpeg"
    if s == ".webp":
        return "image/webp"
    if s == ".bmp":
        return "image/bmp"
    return "application/octet-stream"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=str, default=r"data\inbound\test", help="图片目录（递归）")
    ap.add_argument("--seed", type=int, default=None, help="随机种子（便于复现）")
    ap.add_argument("--model", type=str, default="", help="覆盖 VLM_MODEL（可选）")
    ap.add_argument("--timeout", type=float, default=120.0, help="单次请求超时（秒）")
    ap.add_argument("--json", action="store_true", help="启用 response_format_json（模拟 GUI/流水线调用）")
    args = ap.parse_args()

    root = project_root()
    load_dotenv(root / ".env")

    d = (root / Path(args.dir)).resolve()
    imgs = _list_images(d)
    if not imgs:
        raise SystemExit(f"目录下没有图片: {d}")

    rng = random.Random(args.seed)
    img_path = rng.choice(imgs)

    s = vlm_settings()
    api_key = s["api_key"]
    base_url = s["base_url"]
    model = (args.model or s["mm_model"] or "").strip()
    if not model:
        raise SystemExit("缺少模型名：请在 .env 设置 VLM_MODEL，或用 --model 指定。")

    if not api_key:
        raise SystemExit("缺少 VLM_API_KEY：请在项目根目录 .env 中设置。")

    # 可选：有些网关需要额外 header，可在这里加（保持脚本简单，暂不引入）
    cl = OpenAICompatClient(api_key=api_key, base_url=base_url, timeout=float(args.timeout))

    img_bytes = img_path.read_bytes()
    ctype = _guess_content_type(img_path)

    system = "你是一个图像内容识别助手。"
    user = "请用一句话回答：这张图片是什么？不要输出多余内容。"

    try:
        rel = img_path.relative_to(root)
        picked = str(rel)
    except Exception:
        picked = str(img_path)
    print(f"picked: {picked}")
    print(f"base_url: {base_url or ''}")
    print(f"model: {model}")
    print(f"content_type: {ctype}")

    txt = cl.chat_vision(
        model=model,
        system=system,
        user_text=user,
        image_bytes=img_bytes,
        content_type=ctype,
        temperature=0.0,
        timeout=float(args.timeout),
        response_format_json=bool(args.json),
    )

    if not (txt or "").strip():
        raise SystemExit("VLM 返回为空（empty response body）")

    print("\n--- VLM response ---\n")
    print(txt)


if __name__ == "__main__":
    # Windows 下某些环境变量可能影响代理/证书；保持可见性
    _ = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    main()

