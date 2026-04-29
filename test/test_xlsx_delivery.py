from __future__ import annotations

from pathlib import Path

from delivery_vlm.io.xlsx_delivery import write_delivery_rows_to_xlsx


def test_write_delivery_xlsx(tmp_path: Path) -> None:
    cols = ("page_id", "source_image", "款号", "颜色", "S", "M", "L", "XL", "XXL", "小计")
    p = tmp_path / "d.xlsx"
    write_delivery_rows_to_xlsx(
        p,
        [
            {
                "page_id": "a",
                "source_image": "x.png",
                "款号": "X1",
                "颜色": "红",
                "S": "0",
                "M": "2",
                "L": "",
                "XL": "",
                "XXL": "",
                "小计": "2",
            },
        ],
        columns=cols,
    )
    assert p.is_file()
