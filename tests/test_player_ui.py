from support import temporary_workspace
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import ctypes
from ctypes import wintypes

import numpy as np
import soundfile as sf

from azure_music_player import AzureMusicPlayer


class PlayerUITests(unittest.TestCase):
    def test_last_played_song_and_mode_survive_restart_and_browsing(self):
        from player_settings import load_playback, save_playback
        with temporary_workspace() as folder:
            folder = Path(folder)
            state = folder / 'state.json'
            song = folder / '記住這首.wav'
            sf.write(song, np.zeros(8000), 8000)
            app = AzureMusicPlayer(state_path=state)
            try:
                app.add_paths([str(song)])
                with patch('audio_engine.sd.OutputStream'):
                    app.play_row(app.all_track_rows()[0])
                app.cycle_mode()  # sequence -> shuffle
                self.assertEqual(load_playback(app.settings_path)[0], 'shuffle')
                # Browsing another playlist must not overwrite the played song.
                app.active_playlist = '我的最愛'
                app.render_tracks()
            finally:
                app.close_player()
            restored = AzureMusicPlayer(state_path=state)
            try:
                self.assertEqual(restored.play_mode, 'shuffle')
                self.assertEqual(restored.active_playlist, '預設清單')
                selected = restored.tree.selection()[0]
                self.assertEqual(restored.tree.item(selected, 'values')[3], str(song))
                self.assertEqual(restored.title_text.get(), song.stem)
                self.assertIsNone(restored.audio.file)
                self.assertFalse(restored.playing)
                with patch('audio_engine.sd.OutputStream'):
                    restored.toggle_play()
                self.assertTrue(restored.playing)
                restored.cycle_mode()  # shuffle -> single
            finally:
                restored.close_player()
            single = AzureMusicPlayer(state_path=state)
            try:
                self.assertEqual(single.play_mode, 'single')
                # Removing the remembered song should make the next launch safe.
                single.clear()
            finally:
                single.close_player()
            removed = AzureMusicPlayer(state_path=state)
            try:
                self.assertFalse(removed.tree.selection())
                self.assertIsNone(removed.audio.file)
            finally:
                removed.close_player()
            save_playback(folder / 'settings.json', 'invalid', {'path': 123})
            self.assertEqual(load_playback(folder / 'settings.json'), ('sequence', None))

    def test_collapse_keeps_the_same_native_window_frame(self):
        user32 = ctypes.WinDLL('user32')
        user32.GetParent.argtypes = [wintypes.HWND]
        user32.GetParent.restype = wintypes.HWND
        with temporary_workspace() as folder:
            app = AzureMusicPlayer(state_path=Path(folder) / 'state.json')
            try:
                app.geometry('410x620')
                app.update()
                frame = user32.GetParent(app.winfo_id())
                for _ in range(3):
                    app.toggle_list()
                    app.update()
                    self.assertEqual(user32.GetParent(app.winfo_id()), frame)
                    self.assertEqual(app.winfo_height(), 215)
                    app.geometry('410x500')
                    app.update()
                    self.assertEqual(app.winfo_height(), 215)
                    app.toggle_list()
                    app.update()
                    self.assertEqual(user32.GetParent(app.winfo_id()), frame)
                    self.assertEqual(app.winfo_height(), 620)
            finally:
                app.close_player()

    def test_window_size_and_collapsed_state_survive_restart_with_volume(self):
        with temporary_workspace() as folder:
            state_path = Path(folder) / 'state.json'
            app = AzureMusicPlayer(state_path=state_path)
            try:
                app.geometry('410x620')
                app.update()
                app.set_volume(24)
            finally:
                app.close_player()
            restored = AzureMusicPlayer(state_path=state_path)
            try:
                restored.update()
                self.assertEqual(restored.winfo_height(), 620)
                self.assertEqual(restored.volume_percentage, 24)
                self.assertEqual(str(restored.tree.column('number', 'anchor')), 'center')
                self.assertEqual(str(restored.tree.heading('number', 'anchor')), 'center')
                restored.toggle_list()
                restored.update()
            finally:
                restored.close_player()
            collapsed = AzureMusicPlayer(state_path=state_path)
            try:
                collapsed.update()
                self.assertTrue(collapsed.collapsed)
                self.assertEqual(collapsed.winfo_height(), 215)
                self.assertEqual(collapsed.expanded_height, 620)
                collapsed.toggle_list()
                collapsed.update()
                self.assertEqual(collapsed.winfo_height(), 620)
                collapsed.set_volume(0)
                collapsed.persist_window()
                collapsed.persist_volume()
                from player_settings import load_window
                self.assertEqual(load_window(collapsed.settings_path, 1000), (620, False))
            finally:
                collapsed.close_player()

    def test_filtered_reorder_and_add_keep_hidden_songs(self):
        with temporary_workspace() as folder:
            folder = Path(folder)
            song = folder / 'new.wav'
            sf.write(song, np.zeros(800), 8000)
            app = AzureMusicPlayer(state_path=folder / 'state.json')
            try:
                app.playlists[app.active_playlist] = [(name, '00:01', str(song.resolve()))
                    for name in ('Blue first', 'Hidden', 'Blue last')]
                app.render_tracks()
                app.search_text.set('blue')
                app.update()
                first, last = app.tree.get_children()
                app.drag_active = True
                app.drag_rows = (last,)
                bounds = app.tree.bbox(first)
                app.finish_track_drag(SimpleNamespace(x=50, y=bounds[1]))
                self.assertEqual([track[0] for track in app.playlists[app.active_playlist]],
                                 ['Blue last', 'Hidden', 'Blue first'])
                app.add_paths([str(song)], insert_at=0)
                self.assertEqual(len(app.tree.get_children()), 2)
                self.assertEqual(len(app.playlists[app.active_playlist]), 4)
                self.assertEqual(app.playlists[app.active_playlist][0][0], 'new')
                app.search_text.set('')
                self.assertEqual([app.tree.item(r, 'values')[0] for r in app.tree.get_children()],
                                 ['1', '2', '3', '4'])
            finally:
                app.close_player()

    def test_live_search_preserves_hidden_tracks_playback_and_saved_order(self):
        with temporary_workspace() as folder:
            folder = Path(folder)
            song = folder / 'sound.wav'
            sf.write(song, np.zeros(8000), 8000)
            state_path = folder / 'state.json'
            app = AzureMusicPlayer(state_path=state_path)
            try:
                app.playlists[app.active_playlist] = [(name, '00:01', str(song.resolve())) for name in
                    ('Blue Light', '城市微光', 'Rain notes', 'ＢＬＵＥ mood')]
                app.render_tracks()
                app.search_text.set('blue')
                self.assertEqual(len(app.tree.get_children()), 2)
                app.search_text.set('城光')
                rows = app.tree.get_children()
                self.assertEqual(len(rows), 1)
                self.assertEqual(app.tree.item(rows[0], 'values')[:2], ('2', '城市微光'))
                with patch('audio_engine.sd.OutputStream'):
                    app.play_row(rows[0])
                    self.assertEqual(app.playing_index, 1)
                    audio_file = app.audio.file
                    app.search_text.set('rain')
                    self.assertIs(app.audio.file, audio_file)
                    self.assertEqual(app.title_text.get(), '城市微光')
                    app.change_track(1)
                    self.assertEqual(app.title_text.get(), 'Rain notes')
                app.tree.selection_set(app.tree.get_children()[0])
                app.delete_selected_tracks()
                app.search_text.set('no match')
                self.assertFalse(app.tree.get_children())
                app.save_tracks()
                self.assertEqual(len(app.playlists[app.active_playlist]), 3)
                app.search_text.set('')
                self.assertEqual([app.tree.item(r, 'values')[1] for r in app.tree.get_children()],
                                 ['Blue Light', '城市微光', 'ＢＬＵＥ mood'])
                app.search_text.set('城光')
                app.playlist_list.selection_clear(0, 'end')
                app.playlist_list.selection_set(1)
                app.switch_playlist()
                self.assertFalse(app.tree.get_children())
                app.playlist_list.selection_clear(0, 'end')
                app.playlist_list.selection_set(0)
                app.switch_playlist()
                self.assertEqual(len(app.tree.get_children()), 1)
                app.search_text.set('blue')
            finally:
                app.close_player()
            restored = AzureMusicPlayer(state_path=state_path)
            try:
                self.assertEqual(len(restored.tree.get_children()), 3)
                self.assertEqual(restored.search_text.get(), '')
            finally:
                restored.close_player()

    def test_vertical_resize_and_reveal_context_file(self):
        with temporary_workspace() as folder:
            app = AzureMusicPlayer(state_path=Path(folder) / 'state.json')
            try:
                app.update()
                initial = app.tree.winfo_height()
                top_height = app.cover.master.winfo_height()
                app.geometry('410x650')
                app.update()
                self.assertEqual(app.tree.winfo_height() - initial, 190)
                self.assertEqual(app.cover.master.winfo_height(), top_height)
                app.toggle_list()
                app.update()
                self.assertEqual(app.winfo_height(), 215)
                app.toggle_list()
                app.update()
                self.assertEqual(app.winfo_height(), 650)
                app.geometry('410x360')
                app.update()
                self.assertGreater(app.tree.winfo_height(), 60)
                first_path = str(Path(folder) / '第一首 音樂.mp3')
                second_path = str(Path(folder) / '第二首.mp3')
                first = app.tree.insert('', 'end', values=(1, '第一首', '--:--', first_path))
                second = app.tree.insert('', 'end', values=(2, '第二首', '--:--', second_path))
                app.tree.selection_set((first, second))
                app.tree.focus(second)
                with patch('azure_music_player.reveal_file') as reveal:
                    app.open_file_location()
                    reveal.assert_called_once_with(second_path)
                with patch('azure_music_player.reveal_file', side_effect=FileNotFoundError('missing')):
                    with patch('azure_music_player.messagebox.showerror') as error:
                        app.open_file_location()
                        self.assertTrue(error.called)
            finally:
                app.close_player()

    def test_volume_restore_drop_first_and_delete(self):
        with temporary_workspace() as folder:
            folder = Path(folder)
            paths = [folder / name for name in ('原有.wav', '新增 A.wav', '新增 B.wav')]
            for path in paths:
                sf.write(path, np.zeros(800), 8000)
            originals = {path: path.read_bytes() for path in paths}
            state_path = folder / 'state.json'
            app = AzureMusicPlayer(state_path=state_path)
            try:
                app.add_paths([str(paths[0])])
                app.drop_files(SimpleNamespace(data=app.tk.call('list', *(str(p) for p in paths[1:]))))
                rows = app.tree.get_children()
                self.assertEqual([app.tree.item(r, 'values')[1] for r in rows],
                                 ['新增 A', '新增 B', '原有'])
                app.tree.selection_set(rows[:2])
                app.tree.focus_force()
                app.update()
                app.tree.event_generate('<Delete>')
                app.update()
                self.assertEqual(len(app.tree.get_children()), 1)
                self.assertEqual(app.tree.item(app.tree.get_children()[0], 'values')[:2], ('1', '原有'))
                for path in paths:
                    self.assertEqual(path.read_bytes(), originals[path])
                app.set_volume(27)
            finally:
                app.close_player()
            restored = AzureMusicPlayer(state_path=state_path)
            try:
                self.assertEqual(restored.volume_percentage, 27)
                self.assertEqual(restored.volume_slider.get(), 27)
                self.assertEqual(restored.volume_text.get(), '27%')
                self.assertEqual(restored.audio.volume, 27 / 200)
                self.assertEqual(len(restored.tree.get_children()), 1)
                restored.set_volume(0)
                restored.persist_volume()
                from player_settings import load_volume
                self.assertEqual(load_volume(restored.settings_path), 0)
            finally:
                restored.close_player()

    def test_browse_playlist_preserves_transport_and_marquee(self):
        with temporary_workspace() as folder:
            folder = Path(folder)
            songs = []
            for name in ('first', 'second'):
                path = folder / (name + '.wav')
                sf.write(path, np.zeros(16000), 16000)
                songs.append((name, '00:01', str(path.resolve())))
            app = AzureMusicPlayer(state_path=folder / 'state.json')
            try:
                app.playlists[app.active_playlist] = songs
                app.render_tracks()
                app.update()
                with patch('audio_engine.sd.OutputStream'):
                    app.play_row(app.tree.get_children()[0])
                    original = app.audio.file
                    app.playlist_list.selection_clear(0, 'end')
                    app.playlist_list.selection_set(1)
                    app.switch_playlist()
                    self.assertIs(app.audio.file, original)
                    self.assertTrue(app.playing)
                    self.assertEqual(app.title_text.get(), 'first')
                    app.toggle_play()
                    self.assertTrue(app.audio.paused)
                    app.toggle_play()
                    self.assertFalse(app.audio.paused)
                    app.change_track(1)
                    self.assertEqual(app.title_text.get(), 'second')
                    app.change_track(-1)
                    self.assertEqual(app.title_text.get(), 'first')
                    app.audio.finished.set()
                    app.after_cancel(app.poll_timer)
                    app.poll_audio()
                    self.assertEqual(app.title_text.get(), 'second')
                    self.assertEqual(app.active_playlist, list(app.playlists)[1])
                self.assertEqual(app.playlist_title.get(), '播放清單')
                labels = [app.track_menu.entrycget(i, 'label')
                          for i in range(app.track_menu.index('end') + 1)
                          if app.track_menu.type(i) == 'command']
                self.assertNotIn('清空', labels)
                app.title_text.set('日本語の長い曲名 ' * 20)
                app.update_idletasks()
                before = app.title_marquee.coords(app.title_marquee.item)[0]
                app.title_marquee.after_cancel(app.title_marquee.timer)
                app.title_marquee.step()
                self.assertLess(app.title_marquee.coords(app.title_marquee.item)[0], before)
            finally:
                app.close_player()


if __name__ == '__main__':
    unittest.main()
