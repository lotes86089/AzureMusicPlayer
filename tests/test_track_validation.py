from support import temporary_workspace
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from azure_music_player import AzureMusicPlayer
from track_validation import TrackValidator, validate_track


class TrackValidationTests(unittest.TestCase):
    def test_missing_corrupt_valid_and_recovered_file(self):
        with temporary_workspace() as folder:
            path = str(Path(folder) / '修復.wav')
            validator = TrackValidator()
            try:
                validator.submit([path])
                self.assertTrue(validator.results.get(timeout=3)[path][1])
                Path(path).write_bytes(b'not audio')
                self.assertTrue(validate_track(path))
                sf.write(path, np.zeros(800), 8000)
                validator.submit([path])
                self.assertEqual(validator.results.get(timeout=3)[path][1], '')
                Path(path).unlink()
                validator.submit([path])
                self.assertTrue(validator.results.get(timeout=3)[path][1])
            finally:
                validator.stopped.set()

    def test_warning_survives_selection_numbering_and_playback_failure(self):
        with temporary_workspace() as folder:
            folder = Path(folder)
            good = folder / 'good.wav'
            broken = folder / 'broken.wav'
            missing = folder / 'missing.wav'
            sf.write(good, np.zeros(800), 8000)
            broken.write_bytes(b'invalid audio')
            app = AzureMusicPlayer(state_path=folder / 'state.json')
            try:
                app.add_paths([str(good), str(broken), str(missing)])
                rows = app.tree.get_children()
                self.assertEqual(len(rows), 3)
                self.assertFalse(app.tree.item(rows[0], 'image'))
                self.assertTrue(app.tree.item(rows[1], 'image'))
                self.assertTrue(app.tree.item(rows[2], 'image'))
                app.tree.selection_set(rows[2])
                app.show_track_error()
                self.assertIn('無法讀取', app.status.get())
                app.renumber_tracks()
                self.assertTrue(app.tree.item(rows[2], 'image'))
                with patch.object(app.audio, 'load', side_effect=RuntimeError('decoder failed')):
                    with patch('azure_music_player.messagebox.showerror'):
                        app.play_row(rows[0])
                self.assertTrue(app.tree.item(rows[0], 'image'))
                with patch('audio_engine.sd.OutputStream'):
                    app.play_row(rows[0])
                self.assertFalse(app.tree.item(rows[0], 'image'))
                app.stop()
                self.assertTrue(good.is_file())
                self.assertEqual(broken.read_bytes(), b'invalid audio')
            finally:
                app.close_player()


if __name__ == '__main__':
    unittest.main()
