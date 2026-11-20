"""Explicit taskbar identity and relaunch metadata for the native Tk wrapper."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import hashlib
import sys
import uuid


class GUID(ctypes.Structure):
    _fields_ = [('data', ctypes.c_ubyte * 16)]

    def __init__(self, value):
        super().__init__((ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(value).bytes_le))


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [('fmtid', GUID), ('pid', wintypes.DWORD)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [('vt', ctypes.c_ushort), ('reserved', ctypes.c_ushort * 3),
                ('value', ctypes.c_void_p),
                ('padding', ctypes.c_ubyte * (8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 4))]


IID_STORE = GUID('886d8eeb-8cf2-4446-8d02-cdba1dbdcf99')
APP_PROPERTIES = GUID('9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3')


def _check(result):
    if result < 0:
        raise OSError(f'Windows taskbar HRESULT: 0x{result & 0xffffffff:08X}')


def application_id():
    # Explorer's existing portable-app shortcut uses this exact path as its ID.
    path = str(Path(sys.executable).resolve())
    if not getattr(sys, 'frozen', False):
        return 'AzureMusicPlayer.Development'
    return path if len(path) <= 128 else 'AzureMusicPlayer.' + hashlib.sha256(path.encode()).hexdigest()


def configure_process():
    shell = ctypes.WinDLL('shell32')
    shell.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
    shell.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
    _check(shell.SetCurrentProcessExplicitAppUserModelID(application_id()))


def _window_store(hwnd, values=None):
    ole = ctypes.WinDLL('ole32')
    ole.CoInitialize.argtypes = [ctypes.c_void_p]
    ole.CoInitialize.restype = ctypes.c_long
    initialized = ole.CoInitialize(None)
    if initialized < 0 and initialized != -2147417850:
        _check(initialized)
    shell = ctypes.WinDLL('shell32')
    shell.SHGetPropertyStoreForWindow.argtypes = [wintypes.HWND, ctypes.POINTER(GUID),
                                                 ctypes.POINTER(ctypes.c_void_p)]
    shell.SHGetPropertyStoreForWindow.restype = ctypes.c_long
    store = ctypes.c_void_p()
    try:
        _check(shell.SHGetPropertyStoreForWindow(hwnd, ctypes.byref(IID_STORE), ctypes.byref(store)))
        table = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        def method(index, *types):
            return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *types)(table[index])
        if values is not None:
            for pid, text in values.items():
                key = PROPERTYKEY(APP_PROPERTIES, pid)
                buffer = ctypes.create_unicode_buffer(text)
                variant = PROPVARIANT(vt=31, value=ctypes.cast(buffer, ctypes.c_void_p))
                _check(method(6, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))(
                    store, ctypes.byref(key), ctypes.byref(variant)))
            # Window property stores apply SetValue immediately; Commit is not needed.
        result = {}
        for pid in (2, 3, 4, 5):
            key, variant = PROPERTYKEY(APP_PROPERTIES, pid), PROPVARIANT()
            _check(method(5, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))(
                store, ctypes.byref(key), ctypes.byref(variant)))
            try:
                result[pid] = ctypes.wstring_at(variant.value) if variant.vt == 31 else None
            finally:
                ole.PropVariantClear(ctypes.byref(variant))
        return result
    finally:
        if store:
            table = ctypes.cast(store, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(table[2])(store)
        if initialized >= 0:
            ole.CoUninitialize()


def configure_window(root):
    root.update_idletasks()
    user = ctypes.WinDLL('user32')
    user.GetParent.argtypes = [wintypes.HWND]
    user.GetParent.restype = wintypes.HWND
    hwnd = user.GetParent(root.winfo_id()) or root.winfo_id()
    command = f'"{sys.executable}"'
    if not getattr(sys, 'frozen', False):
        command += f' "{Path(__file__).with_name("azure_music_player.py")}"'
    return _window_store(hwnd, {
        2: command, 3: f'{sys.executable},0', 4: 'AzureMusicPlayer',
        5: application_id(),  # Set identity last, after its relaunch properties.
    })
