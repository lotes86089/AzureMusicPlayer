import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import numpy as np
import soundfile as sf

from azure_music_player import AzureMusicPlayer, DEFAULT_PLAYLIST
from single_instance import SingleInstance
from support import temporary_workspace


class SingleInstanceTests(unittest.TestCase):
    def test_secondary_process_forwards_file_to_original_player(self):
        with temporary_workspace() as folder:
            folder = Path(folder)
            song = folder / '從檔案總管開啟 音樂.wav'
            sf.write(song, np.zeros(8000), 8000)
            namespace = 'test-' + uuid4().hex
            primary = SingleInstance(namespace)
            app = AzureMusicPlayer(state_path=folder / 'state.json', instance=primary)
            try:
                app.active_playlist = '我的最愛'
                app.render_tracks()
                app.search_text.set('old filter')
                script = '''import sys
from single_instance import SingleInstance
instance=SingleInstance(sys.argv[1])
try:
    assert not instance.is_primary
    instance.forward(sys.argv[2:])
finally:
    instance.close()
'''
                with patch('audio_engine.sd.OutputStream'):
                    for _ in range(2):
                        subprocess.run([sys.executable, '-B', '-c', script, namespace, str(song.resolve())],
                                       check=True, timeout=10, capture_output=True)
                        deadline = time.monotonic() + 3
                        while time.monotonic() < deadline:
                            app.update()
                            if app.playing and app.instance.requests.empty():
                                break
                            time.sleep(0.02)
                    self.assertTrue(app.playing)
                    self.assertEqual(app.active_playlist, DEFAULT_PLAYLIST)
                    self.assertEqual(app.search_text.get(), '')
                    self.assertEqual(len(app.playlists[DEFAULT_PLAYLIST]), 1)
                    self.assertEqual(app.title_text.get(), song.stem)
                    original_file = app.audio.file
                    subprocess.run([sys.executable, '-B', '-c', script, namespace],
                                   check=True, timeout=10, capture_output=True)
                    for _ in range(10):
                        app.update()
                        time.sleep(0.02)
                    self.assertIs(app.audio.file, original_file)
            finally:
                app.close_player()
                primary.close()
            replacement = SingleInstance(namespace)
            try:
                self.assertTrue(replacement.is_primary)
            finally:
                replacement.close()

    def test_renamed_legacy_default_is_kept_and_default_is_protected(self):
        with temporary_workspace() as folder:
            state_path = Path(folder) / 'state.json'
            state_path.write_text(json.dumps({'playlists': {'舊清單': []}, 'active_playlist': '舊清單'}),
                                  encoding='utf-8')
            app = AzureMusicPlayer(state_path=state_path)
            try:
                self.assertIn('舊清單', app.playlists)
                self.assertIn(DEFAULT_PLAYLIST, app.playlists)
                app.save_tracks()
                app.active_playlist = DEFAULT_PLAYLIST
                app.render_tracks()
                with patch('azure_music_player.simpledialog.askstring') as rename:
                    app.rename_playlist()
                    rename.assert_not_called()
                with patch('azure_music_player.messagebox.askyesno') as delete:
                    app.delete_playlist()
                    delete.assert_not_called()
                self.assertIn(DEFAULT_PLAYLIST, app.playlists)
            finally:
                app.close_player()


if __name__ == '__main__':
    unittest.main()
