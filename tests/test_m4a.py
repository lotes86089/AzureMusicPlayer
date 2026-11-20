from fractions import Fraction
from pathlib import Path
from support import temporary_workspace
import unittest
from unittest.mock import patch

import av
import numpy as np

from audio_engine import AudioEngine
from audio_formats import M4AFile, audio_info
from azure_music_player import AzureMusicPlayer
from track_validation import validate_track


def make_m4a(path, codec):
    samples = np.stack([np.linspace(-0.3, 0.3, 44100, dtype='float32')] * 2)
    fmt = 'fltp'
    if codec == 'alac':
        samples = (samples * 2**30).astype('int32')
        fmt = 's32p'
    with av.open(str(path), 'w', format='ipod') as container:
        stream = container.add_stream(codec, rate=44100)
        stream.layout = 'stereo'
        frame = av.AudioFrame.from_ndarray(samples, format=fmt, layout='stereo')
        frame.sample_rate = 44100
        frame.pts = 0
        frame.time_base = Fraction(1, 44100)
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)


class M4ATests(unittest.TestCase):
    def test_aac_alac_stream_seek_pause_and_end(self):
        with temporary_workspace() as folder:
            for codec in ('aac', 'alac'):
                with self.subTest(codec=codec):
                    path = Path(folder) / (codec + ' 音樂.m4a')
                    make_m4a(path, codec)
                    original = path.read_bytes()
                    self.assertEqual(validate_track(str(path)), '')
                    self.assertAlmostEqual(audio_info(path).duration, 1.0, places=2)
                    with M4AFile(path) as reader:
                        first = reader.read(256)
                        self.assertEqual(first.shape, (256, 2))
                        self.assertLess(float(first.mean()), -0.1)
                        reader.seek(22050)
                        self.assertLess(abs(float(reader.read(256).mean())), 0.02)
                        self.assertEqual(reader.tell(), 22306)
                        reader.seek(0)
                        self.assertEqual(len(reader.read(100000)), 44100)
                        self.assertEqual(len(reader.read(256)), 0)
                    engine = AudioEngine()
                    try:
                        with patch('audio_engine.sd.OutputStream'):
                            engine.load(path)
                        engine.paused = True
                        output = np.ones((256, 2), dtype='float32')
                        engine._callback(output, 256, None, None)
                        self.assertFalse(output.any())
                        engine.seek(0.5)
                        engine.paused = False
                        engine._callback(output, 256, None, None)
                        self.assertGreater(engine.position, 0.5)
                    finally:
                        engine.close()
                    self.assertEqual(path.read_bytes(), original)

    def test_m4a_add_drop_and_corrupt_warning(self):
        with temporary_workspace() as folder:
            folder = Path(folder)
            good = folder / '歌曲.M4A'
            bad = folder / '壞檔.m4a'
            make_m4a(good, 'aac')
            bad.write_bytes(b'invalid m4a')
            app = AzureMusicPlayer(state_path=folder / 'state.json')
            try:
                app.add_paths([str(good), str(bad)])
                rows = app.tree.get_children()
                self.assertEqual(len(rows), 2)
                self.assertFalse(app.tree.item(rows[0], 'image'))
                self.assertTrue(app.tree.item(rows[1], 'image'))
                with patch('audio_engine.sd.OutputStream'):
                    app.play_row(rows[0])
                self.assertTrue(app.playing)
            finally:
                app.close_player()


if __name__ == '__main__':
    unittest.main()
