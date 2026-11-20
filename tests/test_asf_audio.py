from pathlib import Path
from unittest.mock import Mock
import unittest

import av
import numpy as np
import soundfile as sf

from audio_formats import ASF_HEADER, FFmpegAudioFile, audio_info, open_audio, uses_ffmpeg
from support import temporary_workspace


class ASFAudioTests(unittest.TestCase):
    def test_asf_disguised_as_mp3_decodes_beyond_three_seconds(self):
        with temporary_workspace() as folder:
            raw = Path(folder) / 'raw.mp3'
            disguised = Path(folder) / 'ASF 音樂.mp3'
            sf.write(raw, np.zeros((44100 * 8, 2), dtype='float32'), 44100)
            with av.open(str(raw)) as source:
                with av.open(str(disguised), 'w', format='asf') as output:
                    stream = output.add_stream_from_template(source.streams.audio[0])
                    for packet in source.demux(source.streams.audio[0]):
                        if packet.dts is not None:
                            packet.stream = stream
                            output.mux(packet)
            original = disguised.read_bytes()
            self.assertTrue(original.startswith(ASF_HEADER))
            self.assertTrue(uses_ffmpeg(disguised))
            self.assertFalse(uses_ffmpeg(raw))
            with open_audio(disguised) as audio:
                self.assertIsInstance(audio, FFmpegAudioFile)
                frames = 0
                while True:
                    data = audio.read(4096)
                    frames += len(data)
                    if len(data) < 4096:
                        break
                self.assertGreater(frames / audio.samplerate, 7.9)
                audio.seek(5 * audio.samplerate)
                self.assertEqual(len(audio.read(4096)), 4096)
            self.assertGreater(audio_info(disguised).duration, 7.9)
            self.assertEqual(disguised.read_bytes(), original)

    def test_single_bad_packet_is_skipped_but_many_bad_packets_raise(self):
        reader = FFmpegAudioFile.__new__(FFmpegAudioFile)
        reader.stream = Mock()
        reader.container = Mock()
        reader.skipped_packets = 0
        broken = Mock()
        broken.decode.side_effect = av.error.InvalidDataError(1094995529, 'bad packet')
        valid = Mock()
        frame = object()
        valid.decode.return_value = [frame]
        reader.container.demux.return_value = iter([broken, valid])
        self.assertEqual(list(reader._decode_frames()), [frame])
        self.assertEqual(reader.skipped_packets, 1)
        reader.container.demux.return_value = iter([broken] * 17)
        with self.assertRaises(av.error.InvalidDataError):
            list(reader._decode_frames())


if __name__ == '__main__':
    unittest.main()
