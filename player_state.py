"""Atomic local playlist storage, independent of audio file availability."""
import json
from pathlib import Path


def load_state(path):
    path = Path(path)
    if not path.exists():
        return None
    state = json.loads(path.read_text(encoding='utf-8'))
    playlists = state['playlists']
    if not isinstance(playlists, dict) or not playlists:
        raise ValueError('清單資料無效')
    for name, tracks in playlists.items():
        if not isinstance(name, str) or not isinstance(tracks, list):
            raise ValueError('清單資料無效')
        for track in tracks:
            if not isinstance(track, (list, tuple)) or len(track) != 3 or not all(isinstance(v, str) for v in track):
                raise ValueError('歌曲資料無效')
    active = state.get('active_playlist')
    return playlists, active if active in playlists else next(iter(playlists))


def save_state(path, playlists, active):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'version': 1, 'active_playlist': active,
                                     'playlists': playlists}, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)
