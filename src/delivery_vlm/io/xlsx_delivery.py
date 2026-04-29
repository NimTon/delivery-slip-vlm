from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from openpyxl import Workbook
from openpyxl.utils import get_column_letter


def write_delivery_rows_to_xlsx(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    columns: Sequence[str],
) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    if ws is None:
        return
    ws.title = "delivery"
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
    wb.save(path)
