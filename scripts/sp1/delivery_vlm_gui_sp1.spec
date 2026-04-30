# -*- mode: python ; coding: utf-8 -*-
# SP1：将 delivery-vlm-gui 打成单文件 exe。在仓库根目录执行：
#   pyinstaller --noconfirm --distpath dist/sp1 --workpath build/sp1 scripts/sp1/delivery_vlm_gui_sp1.spec
from pathlib import Path

try:
    from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules
except ImportError as e:  # noqa: BLE001
    raise SystemExit("请先安装 PyInstaller：pip install pyinstaller") from e

block_cipher = None
_here = Path(SPEC).resolve().parent
_ROOT = _here.parent.parent
_SRC = _ROOT / "src"

_hidden = collect_submodules("delivery_vlm")
_cv2_bins = collect_dynamic_libs("cv2")

a = Analysis(
    [str(_here / "gui_entry_sp1.py")],
    pathex=[str(_SRC)],
    binaries=_cv2_bins,
    datas=[(str(_ROOT / "configs" / "default.yaml"), "configs")],
    hiddenimports=_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "paddle", "paddleclas"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="DeliverySlipVLM-GUI-SP1",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
