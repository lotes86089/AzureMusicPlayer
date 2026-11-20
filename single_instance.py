"""One Windows player per login session, with local named-pipe file forwarding."""
import ctypes
from ctypes import wintypes
import getpass
import hashlib
import json
from multiprocessing.connection import Client, Listener
from multiprocessing import AuthenticationError
from queue import Queue
from threading import Event, Thread
import time


class SingleInstance:
    def __init__(self, namespace='AzureMusicPlayer'):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        kernel.GetCurrentProcessId.restype = wintypes.DWORD
        kernel.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        session = wintypes.DWORD()
        kernel.ProcessIdToSessionId(kernel.GetCurrentProcessId(), ctypes.byref(session))
        identity = f'{namespace}:{getpass.getuser()}:{session.value}'.encode('utf-8')
        digest = hashlib.sha256(identity).hexdigest()
        self.address = r'\\.\pipe\AzureMusicPlayer-' + digest[:24]
        self.authkey = hashlib.sha256(b'AzureMusicPlayer IPC:' + identity).digest()
        self.kernel = kernel
        self.handle = kernel.CreateMutexW(None, False, 'Local\\AzureMusicPlayer-' + digest[:24])
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.is_primary = ctypes.get_last_error() != 183
        self.requests = Queue()
        self.stopped = Event()
        self.listener = None
        self.thread = None
        if self.is_primary:
            try:
                self.listener = Listener(self.address, family='AF_PIPE', authkey=self.authkey)
                self.thread = Thread(target=self._listen, daemon=True)
                self.thread.start()
            except Exception:
                self.close()
                raise

    def _listen(self):
        while True:
            try:
                with self.listener.accept() as connection:
                    if self.stopped.is_set():
                        break
                    if not connection.poll(3):
                        continue
                    paths = json.loads(connection.recv_bytes(1024 * 1024).decode('utf-8'))
                    if not isinstance(paths, list) or len(paths) > 1000:
                        continue
                    if not all(isinstance(path, str) and len(path) <= 32768 for path in paths):
                        continue
                    self.requests.put(paths)
                    connection.send_bytes(b'OK')
            except (OSError, EOFError, ValueError, TypeError, AuthenticationError, AttributeError):
                if self.stopped.is_set():
                    break

    def forward(self, paths):
        error = None
        for _ in range(30):
            try:
                with Client(self.address, family='AF_PIPE', authkey=self.authkey) as connection:
                    connection.send_bytes(json.dumps(list(paths), ensure_ascii=False).encode('utf-8'))
                    if connection.poll(3) and connection.recv_bytes(16) == b'OK':
                        return
                    raise OSError('播放器未回應')
            except (OSError, EOFError) as exc:
                error = exc
                time.sleep(0.1)
        raise OSError('無法連線到已開啟的 AzureMusicPlayer') from error

    def close(self):
        self.stopped.set()
        if self.listener is not None:
            if self.thread is not None and self.thread.is_alive():
                # Wake the outstanding Windows ConnectNamedPipe before closing its listener.
                try:
                    with Client(self.address, family='AF_PIPE', authkey=self.authkey):
                        pass
                except (OSError, EOFError, AuthenticationError):
                    pass
                self.thread.join(timeout=2)
            self.listener.close()
            self.listener = None
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
