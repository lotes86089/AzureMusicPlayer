# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

# Runtime hooks collect theme assets, libsndfile, PortAudio and PyAV's dependent DLLs.
# Match this Windows x64 / Tcl 8 build rather than bundling every OS and architecture.
datas = collect_data_files('tkinterdnd2', includes=['tkdnd/win-x64/*'])
datas += copy_metadata('av')
datas += [('assets/AzureMusicPlayer.png', 'assets'),
          ('assets/AzureMusicPlayer.ico', 'assets')]
binaries = []
hiddenimports = []

a = Analysis(
    ['azure_music_player.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'setuptools', 'pkg_resources', 'distutils', 'pip', 'ensurepip',
        'idlelib', 'tkinter.test', 'unittest', 'doctest', 'pydoc',
        'PIL.AvifImagePlugin', 'PIL._avif',
        'ttkbootstrap.cli', 'ttkbootstrap.__main__', 'ttkbootstrap.convert_theme',
    ],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AzureMusicPlayer',
    icon='assets/AzureMusicPlayer.ico',
    version='AzureMusicPlayer.version.txt',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
