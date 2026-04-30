from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from delivery_vlm.pipeline.delivery_run import run_delivery_vlm_to_xlsx


def main() -> None:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("-v", "--verbose", action="store_true", help="调试日志 (DEBUG)")
    parent.add_argument("-q", "--quiet", action="store_true", help="仅警告与错误 (WARNING)")
    parser = argparse.ArgumentParser(
        prog="delivery-vlm",
        description="送货单：多模态读图结构化 JSON，合并导出 xlsx（无 LLM 修正）",
        parents=[parent],
    )
    parser.add_argument("--in", dest="input_dir", type=Path, required=True, help="输入图片目录（递归扫描）")
    parser.add_argument(
        "--out-dir",
        dest="out_dir",
        type=Path,
        default=None,
        help="输出根目录（默认：项目下 data/out/delivery_vlm）",
    )
    parser.add_argument("--config", dest="config", type=Path, default=None, help="覆盖默认 configs/default.yaml")
    parser.add_argument("--model", dest="mm_model", type=str, default=None, help="覆盖 VLM 模型名（否则取 yaml / VLM_MODEL）")
    parser.add_argument(
        "--out-xlsx",
        dest="out_xlsx",
        type=Path,
        default=None,
        help="合并 xlsx 路径（默认：若未指定 --out-dir 则输出到输入目录；否则为 <out-dir>/delivery_merged.xlsx）",
    )
    parser.add_argument("--out-jsonl", dest="out_jsonl", type=Path, default=None, help="可选：合并行 jsonl")
    args = parser.parse_args()

    level = logging.INFO
    if args.verbose:
        level = logging.DEBUG
    elif args.quiet:
        level = logging.WARNING
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    config_overrides: dict[str, Any] = {}
    co = config_overrides if config_overrides else None

    summary = run_delivery_vlm_to_xlsx(
        input_dir=args.input_dir,
        out_dir=args.out_dir,
        config_path=args.config,
        model=args.mm_model,
        out_xlsx=args.out_xlsx,
        out_jsonl=args.out_jsonl,
        config_overrides=co,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary.get("cancelled"):
        sys.exit(2)


if __name__ == "__main__":
    main()
