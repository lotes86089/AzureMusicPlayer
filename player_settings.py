"""Small atomic settings file stored beside playlist data."""
import json
import math
from pathlib import Path


def _read_settings(path):
    try:
        settings = json.loads(Path(path).read_text(encoding='utf-8'))
        return settings if isinstance(settings, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _update_settings(path, changes):
    settings = _read_settings(path)
    settings.update(changes)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(settings, indent=2), encoding='utf-8')
    temporary.replace(path)


def load_window(path, maximum_height):
    window = _read_settings(path).get('window', {})
    if not isinstance(window, dict):
        window = {}
    height = window.get('height', 460)
    if isinstance(height, bool) or not isinstance(height, (int, float)) or not math.isfinite(height):
        height = 460
    return min(max(360, int(height)), max(360, maximum_height)), window.get('collapsed') is True


def save_window(path, height, collapsed):
    _update_settings(path, {'window': {'width': 410, 'height': height, 'collapsed': collapsed}})


def load_volume(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))['volume']
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return 65.0
        return max(0.0, min(100.0, float(value)))
    except (OSError, ValueError, KeyError, TypeError):
        return 65.0


def save_volume(path, volume):
    _update_settings(path, {'volume': volume})


def load_playback(path):
    settings = _read_settings(path)
    mode = settings.get('play_mode')
    if mode not in ('single', 'sequence', 'shuffle'):
        mode = 'sequence'
    last = settings.get('last_played')
    if not isinstance(last, dict) or not all(isinstance(last.get(key), str)
                                            for key in ('playlist', 'path')):
        last = None
    return mode, last


def save_playback(path, mode, last):
    _update_settings(path, {'play_mode': mode, 'last_played': last})
