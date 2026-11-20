"""Stream M4A and ASF-wrapped audio with FFmpeg; use SoundFile for other files."""
from pathlib import Path
from types import SimpleNamespace
import av
import numpy as np
import soundfile as sf

SUPPORTED_EXTENSIONS = ('.mp3', '.wav', '.flac', '.m4a')


ASF_HEADER = bytes.fromhex('3026b2758e66cf11a6d900aa0062ce6c')


def uses_ffmpeg(path):
    if Path(path).suffix.lower() == '.m4a':
        return True
    # Some legacy music has an .mp3 extension but is actually MP3 wrapped in ASF.
    with open(path, 'rb') as source:
        return source.read(16) == ASF_HEADER


class FFmpegAudioFile:
    def __init__(self, path):
        self.container = av.open(str(path))
        try:
            if not self.container.streams.audio:
                raise ValueError('檔案沒有音訊軌')
            self.stream = self.container.streams.audio[0]
            self.samplerate = self.stream.codec_context.sample_rate
            self.channels = self.stream.codec_context.layout.nb_channels
            if not self.samplerate or not self.channels:
                raise ValueError('無法辨識音訊格式')
            if self.stream.duration is not None:
                duration = float(self.stream.duration * self.stream.time_base)
            elif self.container.duration is not None:
                duration = self.container.duration / av.time_base
            else:
                raise ValueError('無法辨識音樂長度')
            self.frames = round(duration * self.samplerate)
            self.start = float((self.stream.start_time or 0) * self.stream.time_base)
            self.closed = False
            self._reset(0)
        except Exception:
            self.container.close()
            raise

    def __len__(self):
        return self.frames

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _reset(self, target):
        self._position = target
        self._target = target
        self._pending = np.empty((0, self.channels), dtype='float32')
        self.skipped_packets = 0
        self._decoder = self._decode_frames()
        self._resampler = av.AudioResampler(format='flt', layout=self.stream.codec_context.layout,
                                            rate=self.samplerate)
        self._blocks = self._decoded_blocks()

    def _decode_frames(self):
        consecutive_errors = 0
        for packet in self.container.demux(self.stream):
            try:
                frames = packet.decode()
            except av.error.InvalidDataError:
                self.skipped_packets += 1
                consecutive_errors += 1
                if consecutive_errors > 16:
                    raise
                continue
            if frames:
                consecutive_errors = 0
            yield from frames

    def _decoded_blocks(self):
        for frame in self._decoder:
            for converted in self._resampler.resample(frame):
                data = converted.to_ndarray().reshape(-1, self.channels)
                if converted.pts is not None:
                    start = round((float(converted.pts * converted.time_base) - self.start) * self.samplerate)
                    skip = max(0, self._target - start)
                    data = data[skip:]
                if len(data):
                    yield data

    def read(self, frames, dtype='float32', always_2d=True):
        if self.closed:
            raise ValueError('音樂檔已關閉')
        remaining = min(frames, max(0, self.frames - self._position))
        pieces = []
        while remaining:
            if not len(self._pending):
                self._pending = next(self._blocks, None)
                if self._pending is None:
                    self._pending = np.empty((0, self.channels), dtype='float32')
                    break
            count = min(remaining, len(self._pending))
            pieces.append(self._pending[:count])
            self._pending = self._pending[count:]
            remaining -= count
        data = np.concatenate(pieces) if pieces else np.empty((0, self.channels), dtype='float32')
        self._position += len(data)
        data = data.astype(dtype, copy=False)
        return data[:, 0] if not always_2d and self.channels == 1 else data

    def tell(self):
        return self._position

    def seek(self, frame):
        target = min(max(0, int(frame)), self.frames)
        timestamp = int((target / self.samplerate + self.start) / self.stream.time_base)
        self.container.seek(timestamp, stream=self.stream, backward=True)
        self._reset(target)
        return target

    def close(self):
        self.container.close()
        self.closed = True


M4AFile = FFmpegAudioFile  # Compatibility for the existing M4A regression tests.


def open_audio(path):
    return FFmpegAudioFile(path) if uses_ffmpeg(path) else sf.SoundFile(str(path), mode='r')


def audio_info(path):
    if not uses_ffmpeg(path):
        return sf.info(path)
    with FFmpegAudioFile(path) as audio:
        return SimpleNamespace(duration=audio.frames / audio.samplerate)
