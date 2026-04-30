from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from openpyxl import Workbook
from openpyxl.utils import get_column_letter

from delivery_vlm.delivery_schema import XLSX_ORIGINAL_IMAGE_PATH_COLUMN


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
        name = cols[c - 1]
        if name == XLSX_ORIGINAL_IMAGE_PATH_COLUMN:
            w = 48
        elif c <= 2:
            w = 14
        else:
            w = min(50, 18)
        ws.column_dimensions[get_column_letter(c)].width = w


def write_delivery_workbook_to_xlsx(
    path: Path,
    *,
    sheets: Sequence[tuple[Any, ...]],
) -> None:
    """
    写入一个包含多个 sheet 的 xlsx。

    sheets: ``(sheet名, rows, columns)``。
    """
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    if wb.worksheets:
        wb.remove(wb.worksheets[0])
    for spec in sheets:
        if len(spec) != 3:
            raise TypeError(f"sheet 元组长度须为 3: {spec!r}")
        title, rows, cols = spec[0], spec[1], spec[2]
        _write_sheet(
            wb,
            title=str(title),
            rows=list(rows),
            columns=cols,
        )
    wb.save(path)


def write_delivery_rows_to_xlsx(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    columns: Sequence[str],
) -> None:
    """兼容旧接口：单 sheet 写入（sheet 名 delivery，不嵌图）。"""
    write_delivery_workbook_to_xlsx(path, sheets=[("delivery", rows, columns)])
