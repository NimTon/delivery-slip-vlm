from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from openpyxl import Workbook
from openpyxl.utils import get_column_letter


def _write_sheet(
    wb: Workbook,
    *,
    title: str,
    rows: list[dict[str, Any]],
    columns: Sequence[str],
) -> None:
    ws = wb.create_sheet(title=title)
    cols = tuple(columns)
    for c, h in enumerate(cols, start=1):
        ws.cell(row=1, column=c, value=h)
    for r, row in enumerate(rows, start=2):
        for c, key in enumerate(cols, start=1):
            v = row.get(key, "")
            if v is None:
                v = ""
            ws.cell(row=r, column=c, value=v)
    for c in range(1, len(cols) + 1):
        w = 14 if c <= 2 else min(50, 18)
        ws.column_dimensions[get_column_letter(c)].width = w


def write_delivery_workbook_to_xlsx(
    path: Path,
    *,
    sheets: Sequence[tuple[str, list[dict[str, Any]], Sequence[str]]],
) -> None:
    """
    写入一个包含多个 sheet 的 xlsx。

    sheets: [(sheet_name, rows, columns), ...]
    """
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    # 删除默认空白 sheet
    if wb.worksheets:
        wb.remove(wb.worksheets[0])
    for title, rows, cols in sheets:
        _write_sheet(wb, title=title, rows=rows, columns=cols)
    wb.save(path)


def write_delivery_rows_to_xlsx(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    columns: Sequence[str],
) -> None:
    """兼容旧接口：单 sheet 写入（sheet 名固定为 delivery）。"""
    write_delivery_workbook_to_xlsx(path, sheets=[("delivery", rows, columns)])
