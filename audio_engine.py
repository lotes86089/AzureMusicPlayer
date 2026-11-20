"""Decode ahead on a worker; the PortAudio callback only consumes PCM memory."""
from collections import deque
import threading
import numpy as np
import sounddevice as sd
from audio_formats import open_audio


class AudioEngine:
    BUFFER_SECONDS = 3
    PREFILL_SECONDS = 1
    BLOCK_SECONDS = 0.1

    def __init__(self):
        self.stream = None
        self.file = None
        self.volume = 0.65
        self.paused = False
        self.finished = threading.Event()
        self.error = None
        self.lock = threading.Lock()
        self._decode_lock = threading.Lock()
        self._wake = threading.Condition(self.lock)
        self._stop = threading.Event()
        self._worker = None
        self._blocks = deque()
        self._buffered = 0
        self._position = 0
        self._eof = False
        self._seeking = False
        self.underruns = 0

    @property
    def duration(self):
        return len(self.file) / self.file.samplerate if self.file else 0.0

    @property
    def position(self):
        with self.lock:
            return self._position / self.file.samplerate if self.file else 0.0

    def _prefill(self):
        data = self.file.read(max(1, int(self.file.samplerate * self.PREFILL_SECONDS)),
                              dtype='float32', always_2d=True)
        with self.lock:
            if len(data):
                self._blocks.append(data)
                self._buffered += len(data)
            self._eof = len(data) < int(self.file.samplerate * self.PREFILL_SECONDS)

    def load(self, path):
        self.close()
        self.finished.clear()
        self.error = None
        self.paused = False
        self.underruns = 0
        self._stop.clear()
        try:
            self.file = open_audio(path)
            self._prefill()
            self._worker = threading.Thread(target=self._decode, name='AzureMusicDecode', daemon=True)
            self._worker.start()
            self.stream = sd.OutputStream(samplerate=self.file.samplerate,
                                          channels=self.file.channels, dtype='float32',
                                          latency='high', callback=self._callback,
                                          finished_callback=self.finished.set)
            self.stream.start()
        except Exception:
            self.close()
            raise

    def _decode(self):
        while not self._stop.is_set():
            with self._wake:
                self._wake.wait_for(lambda: self._stop.is_set() or
                                    (not self._eof and self._buffered < self.file.samplerate * self.BUFFER_SECONDS))
            if self._stop.is_set():
                return
            # Only the worker and seek use this lock; the audio callback never does.
            with self._decode_lock:
                if self._stop.is_set():
                    return
                try:
                    size = max(1, int(self.file.samplerate * self.BLOCK_SECONDS))
                    data = self.file.read(size, dtype='float32', always_2d=True)
                    with self.lock:
                        if len(data):
                            self._blocks.append(data)
                            self._buffered += len(data)
                        self._eof = len(data) < size
                except Exception as exc:
                    with self.lock:
                        self.error = str(exc)
                        self._eof = True

    def _callback(self, output, frames, time_info, status):
        output.fill(0)
        if self.paused or self._seeking:
            return
        # No file I/O, decoding or waiting for the producer in this callback.
        with self._wake:
            offset = 0
            while self._blocks and offset < frames:
                data = self._blocks[0]
                count = min(len(data), frames - offset)
                np.multiply(data[:count], self.volume, out=output[offset:offset + count])
                if count == len(data):
                    self._blocks.popleft()
                else:
                    self._blocks[0] = data[count:]
                self._buffered -= count
                self._position += count
                offset += count
            self._wake.notify()
            if offset < frames:
                if self._eof:
                    raise sd.CallbackStop
                # A temporary empty buffer is not the end of a track.
                self.underruns += 1

    def seek(self, seconds):
        if not self.file:
            return
        self._seeking = True
        try:
            with self._decode_lock:
                frame = min(max(0, int(seconds * self.file.samplerate)), max(0, len(self.file) - 1))
                self.file.seek(frame)
                with self.lock:
                    self._blocks.clear()
                    self._buffered = 0
                    self._position = frame
                    self._eof = False
                    self.error = None
                self._prefill()
        finally:
            self._seeking = False
            with self._wake:
                self._wake.notify()

    def close(self):
        if self.stream:
            self.stream.abort()
            self.stream.close()
            self.stream = None
        self._stop.set()
        with self._wake:
            self._wake.notify_all()
        if self._worker:
            self._worker.join()
            self._worker = None
        if self.file:
            self.file.close()
            self.file = None
        with self.lock:
            self._blocks.clear()
            self._buffered = 0
            self._position = 0
            self._eof = False
        self.finished.clear()
        self.paused = False
