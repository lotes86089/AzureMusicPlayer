from support import temporary_workspace
import unittest
from pathlib import Path

from player_state import load_state, save_state
from playlist_io import read_ttpl, write_ttpl


class PlaylistTests(unittest.TestCase):
    def test_unicode_ttpl_roundtrip_and_missing_files(self):
        with temporary_workspace() as folder:
            folder = Path(folder)
            tracks = [('神凪 & "日本語"', '02:20', str((folder / '神凪.mp3').resolve()))]
            path = folder / 'list.ttpl'
            write_ttpl(path, 'お気に入り', tracks)
            self.assertEqual(read_ttpl(path), ('お気に入り', tracks))

    def test_state_preserves_order_active_and_missing_tracks(self):
        with temporary_workspace() as folder:
            path = Path(folder) / 'data' / 'playlists.json'
            playlists = {'Like': [('日本語', '02:00', 'D:/missing.mp3')], 'Empty': []}
            save_state(path, playlists, 'Empty')
            restored, active = load_state(path)
            self.assertEqual(list(restored), ['Like', 'Empty'])
            self.assertEqual(tuple(restored['Like'][0]), playlists['Like'][0])
            self.assertEqual(active, 'Empty')
            self.assertFalse(path.with_suffix('.tmp').exists())


if __name__ == '__main__':
    unittest.main()
