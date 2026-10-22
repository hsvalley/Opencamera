# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

# build_exe.ps1 会先 Push-Location 到仓库根目录，故此处用 cwd 定位
project_root = Path.cwd()
python_dir = project_root / "OpenCamera_c" / "python"
dll_path = project_root / "OpenCamera_c" / "c_bridge" / "c_model_bridge.dll"

block_cipher = None


a = Analysis(
    [str(python_dir / "infrared_camera_player.py")],
    pathex=[str(python_dir)],
    binaries=[(str(dll_path), ".")],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name="InfraredCameraPlayerC",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    onefile=True,
)
