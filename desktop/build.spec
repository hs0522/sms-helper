# -*- mode: python ; coding: utf-8 -*-
"""마래푸 문자 도우미 — 윈도우 미니 위젯 PyInstaller 빌드.

    python -m PyInstaller --noconfirm --clean desktop/build.spec

빌드 직전에 prepare_www 가 웹 앱(v1.4.9)을 desktop/www 로 복사하고
위젯 상단 바를 주입한다. 산출물: dist/MaraepuSmsHelper/MaraepuSmsHelper.exe
"""

import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

_spec = globals().get("SPEC") or globals().get("__file__") or os.path.join(os.getcwd(), "build.spec")
HERE = os.path.dirname(os.path.abspath(_spec))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import prepare_www  # noqa: E402

WWW = os.path.join(HERE, "www")
prepare_www.prepare(WWW)

datas = [(WWW, "www")]
datas += copy_metadata("pywebview")

_pythonnet_datas, _pythonnet_binaries, _pythonnet_hidden = collect_all("pythonnet")
datas += _pythonnet_datas
binaries = list(_pythonnet_binaries)

hiddenimports = [
    "clr",
    "clr_loader",
    "webview.platforms.edgechromium",
]
hiddenimports += collect_submodules("webview")
hiddenimports += _pythonnet_hidden

ICON = os.path.join(HERE, "assets", "icon.ico")

a = Analysis(
    [os.path.join(HERE, "widget.py")],
    pathex=[HERE],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MaraepuSmsHelper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MaraepuSmsHelper",
)
