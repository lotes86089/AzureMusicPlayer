"""Decoder and transport regression tests; no physical audio output is opened."""
from support import temporary_workspace
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import sounddevice as sd
import soundfile as sf

from audio_engine import AudioEngine


class AudioEngineTests(unittest.TestCase):
    def test_callback_keeps_playing_when_decoder_is_stalled(self):
        with temporary_workspace() as folder:
            path = Path(folder) / 'buffer.wav'
            sf.write(path, np.full((32000, 2), 0.2, dtype='float32'), 8000)
            engine = AudioEngine()
            try:
                with patch('audio_engine.sd.OutputStream') as stream:
                    engine.load(path)
                self.assertEqual(stream.call_args.kwargs['latency'], 'high')
                # Holding the decoder lock simulates slow disk/decoder work.
                # The callback must still produce half a second of buffered sound.
                with engine._decode_lock:
                    output = np.zeros((4000, 2), dtype='float32')
                    with patch.object(engine.file, 'read', side_effect=AssertionError('callback read')):
                        engine._callback(output, len(output), None, None)
                    self.assertTrue((output > 0).all())
                    self.assertAlmostEqual(engine.position, 0.5)
                    self.assertEqual(engine.underruns, 0)
                    self.assertGreaterEqual(engine._buffered, 4000)
            finally:
                engine.close()
            self.assertIsNone(engine._worker)

    def test_temporary_empty_buffer_does_not_finish_track(self):
        with temporary_workspace() as folder:
            path = Path(folder) / 'recover.wav'
            sf.write(path, np.full((32000, 2), 0.2, dtype='float32'), 8000)
            engine = AudioEngine()
            try:
                with patch('audio_engine.sd.OutputStream'):
                    engine.load(path)
                with engine._decode_lock:
                    with engine.lock:
                        engine._blocks.clear()
                        engine._buffered = 0
                        engine._eof = False
                    output = np.zeros((256, 2), dtype='float32')
                    engine._callback(output, len(output), None, None)
                    self.assertFalse(output.any())
                    self.assertFalse(engine.finished.is_set())
                    self.assertEqual(engine.underruns, 1)
                engine.seek(1.5)
                engine._callback(output, len(output), None, None)
                self.assertTrue((output > 0).all())
                self.assertAlmostEqual(engine.position, 1.532)
            finally:
                engine.close()

    def test_formats_gain_pause_seek_and_original_file(self):
        # Keep fixtures under this project for restricted Windows environments.
        with temporary_workspace() as folder:
            samples = np.full((8000, 2), 0.2, dtype='float32')
            for extension in ('wav', 'flac', 'mp3'):
                with self.subTest(format=extension):
                    path = Path(folder) / ('音樂.' + extension)
                    sf.write(path, samples, 8000)
                    original = path.read_bytes()
                    engine = AudioEngine()
                    try:
                        with patch('audio_engine.sd.OutputStream'):
                            engine.load(path)
                        self.assertAlmostEqual(engine.duration, 1.0, places=2)
                        engine.volume = 0.25
                        output = np.zeros((256, 2), dtype='float32')
                        engine._callback(output, 256, None, None)
                        self.assertGreater(float(np.max(np.abs(output))), 0)
                        self.assertLess(float(np.max(np.abs(output))), 0.1)
                        engine.paused = True
                        position = engine.position
                        engine._callback(output, 256, None, None)
                        self.assertFalse(output.any())
                        self.assertEqual(engine.position, position)
                        engine.seek(0.5)
                        self.assertAlmostEqual(engine.position, 0.5, places=2)
                        engine.paused = False
                        engine.seek(0.999)
                        with self.assertRaises(sd.CallbackStop):
                            engine._callback(output, 256, None, None)
                        self.assertEqual(path.read_bytes(), original)
                    finally:
                        engine.close()

    def test_missing_file_releases_resources(self):
        engine = AudioEngine()
        with self.assertRaises(Exception):
            engine.load(Path(__file__).parent / 'does-not-exist.mp3')
        self.assertIsNone(engine.file)
        self.assertIsNone(engine.stream)


if __name__ == '__main__':
    unittest.main()
