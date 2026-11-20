"""Generate test fixtures locally and remove them after each test."""
from contextlib import contextmanager
from pathlib import Path
import tempfile


@contextmanager
def temporary_workspace():
    root = Path(__file__).parent / '.tmp'
    root.mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=root) as folder:
            yield folder
    finally:
        try:
            root.rmdir()
        except OSError:
            pass
