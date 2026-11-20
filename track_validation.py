"""Background checks never touch Tk widgets or change audio files."""
from pathlib import Path
from queue import Queue, Empty, Full
from threading import Event, Thread
from audio_formats import open_audio


def validate_track(path):
    try:
        if not Path(path).is_file():
            return '檔案不存在或無法存取'
        with open_audio(path) as audio:
            if audio.frames <= 0 or not len(audio.read(256)):
                return '音樂檔案沒有可播放內容'
        return ''
    except Exception as exc:
        return '無法讀取音樂：' + str(exc)


class TrackValidator:
    def __init__(self):
        self.requests = Queue(maxsize=1)
        self.results = Queue(maxsize=1)
        self.stopped = Event()
        Thread(target=self._run, daemon=True).start()

    def submit(self, paths):
        try:
            self.requests.put_nowait(tuple(dict.fromkeys(paths)))
        except Full:
            pass

    def _run(self):
        cache = {}
        while not self.stopped.is_set():
            try:
                paths = self.requests.get(timeout=0.5)
            except Empty:
                continue
            result = {}
            for path in paths:
                if self.stopped.is_set():
                    return
                try:
                    stat = Path(path).stat()
                    signature = (stat.st_mtime_ns, stat.st_size)
                except OSError:
                    signature = None
                previous = cache.get(path)
                error = previous[1] if previous and previous[0] == signature else validate_track(path)
                result[path] = (signature, error)
            cache = result
            try:
                self.results.get_nowait()
            except Empty:
                pass
            self.results.put_nowait(result)
