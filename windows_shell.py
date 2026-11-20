"""Reveal a Unicode file path in Explorer using the Windows Shell API."""
import ctypes
from ctypes import wintypes
from pathlib import Path


def reveal_file(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError('歌曲檔案不存在：' + str(path))
    shell = ctypes.WinDLL('shell32')
    ole = ctypes.WinDLL('ole32')
    ole.CoInitialize.argtypes = [ctypes.c_void_p]
    ole.CoInitialize.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.restype = None
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    shell.SHParseDisplayName.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p,
                                         ctypes.POINTER(ctypes.c_void_p), wintypes.DWORD,
                                         ctypes.c_void_p]
    shell.SHParseDisplayName.restype = ctypes.c_long
    shell.SHOpenFolderAndSelectItems.argtypes = [ctypes.c_void_p, wintypes.UINT,
                                                 ctypes.c_void_p, wintypes.DWORD]
    shell.SHOpenFolderAndSelectItems.restype = ctypes.c_long
    initialized = ole.CoInitialize(None)
    pidl = ctypes.c_void_p()
    try:
        if initialized < 0 and initialized != -2147417850:  # Already in another COM apartment is OK.
            raise OSError(f'無法啟用檔案總管服務：0x{initialized & 0xffffffff:08X}')
        result = shell.SHParseDisplayName(str(path), None, ctypes.byref(pidl), 0, None)
        if result < 0:
            raise OSError(f'無法定位歌曲檔案：0x{result & 0xffffffff:08X}')
        result = shell.SHOpenFolderAndSelectItems(pidl, 0, None, 0)
        if result < 0:
            raise OSError(f'無法開啟檔案總管：0x{result & 0xffffffff:08X}')
    finally:
        if pidl:
            ole.CoTaskMemFree(pidl)
        if initialized >= 0:
            ole.CoUninitialize()
