"""SP1：PyInstaller 冻结入口，仅启动 GUI。"""
from __future__ import annotations

from delivery_vlm.gui_app import main

if __name__ == "__main__":
    main()
