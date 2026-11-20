import ctypes
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from azure_music_player import AzureMusicPlayer
from support import temporary_workspace
from windows_identity import application_id, configure_window, _window_store


class WindowsIdentityTests(unittest.TestCase):
    def test_native_wrapper_identity_and_relaunch_survive_collapse(self):
        executable = str(Path('release/AzureMusicPlayer.exe').resolve())
        with temporary_workspace() as folder:
            app = AzureMusicPlayer(state_path=Path(folder) / 'state.json')
            try:
                with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', executable):
                    values = configure_window(app)
                    self.assertEqual(application_id(), executable)
                    self.assertEqual(values, {2: f'"{executable}"', 3: executable + ',0',
                                              4: 'AzureMusicPlayer', 5: executable})
                user = ctypes.WinDLL('user32')
                user.GetParent.argtypes = [ctypes.c_void_p]
                user.GetParent.restype = ctypes.c_void_p
                for _ in range(2):
                    app.toggle_list()
                    app.update_idletasks()
                    self.assertEqual(_window_store(user.GetParent(app.winfo_id())), values)
            finally:
                app.close_player()
