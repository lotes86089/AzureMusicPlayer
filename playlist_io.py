"""Read extended M3U in UTF-8 or traditional Chinese Windows encoding."""
from pathlib import Path
import xml.etree.ElementTree as ET


def read_ttpl(path):
    path = Path(path)
    root = ET.parse(path).getroot()
    if root.tag != 'ttplaylist':
        raise ValueError('不是有效的 TTPL 播放清單。')
    tracks = []
    for item in root.findall('./items/item'):
        source = item.get('file', '')
        if not source:
            continue
        source = Path(source)
        if not source.is_absolute():
            source = path.parent / source
        title = item.get('title') or source.stem
        if '?' in title and '?' not in source.stem:
            title = source.stem
        seconds = max(0, int(item.get('len', '0'))) // 1000
        tracks.append((title, f'{seconds // 60:02}:{seconds % 60:02}', str(source.resolve())))
    return root.get('title') or path.stem, tracks


def write_ttpl(path, title, tracks):
    root = ET.Element('ttplaylist', title=title, version='4', generator='AzureMusicPlayer')
    ET.SubElement(root, 'format', tagtitle='%A - %T', deftitle='%F')
    items = ET.SubElement(root, 'items', count=str(len(tracks)))
    for name, duration, source in tracks:
        minutes, seconds = duration.split(':')
        ET.SubElement(items, 'item', file=str(Path(source).resolve()), title=name,
                      len=str((int(minutes) * 60 + int(seconds)) * 1000))
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)


def read_m3u(path):
    path = Path(path)
    raw = path.read_bytes()
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        text = raw.decode('utf-16')
    else:
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            candidates = []
            for encoding in ('cp950', 'cp932'):
                try:
                    decoded = raw.decode(encoding)
                except UnicodeDecodeError:
                    continue
                # Legacy M3U has no universal encoding marker. Prefer the
                # decoding whose file paths resolve on this computer.
                score = 0
                for line in decoded.splitlines():
                    line = line.strip()
                    if line and not line.startswith('#'):
                        item = Path(line)
                        try:
                            score += (item if item.is_absolute() else path.parent / item).is_file()
                        except OSError:
                            pass
                candidates.append((score, decoded))
            if not candidates:
                raise ValueError('無法辨識清單編碼，請另存為 UTF-8 M3U。')
            text = max(candidates, key=lambda item: item[0])[1]
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        item = Path(line)
        if not item.is_absolute():
            item = path.parent / item
        entries.append(str(item.resolve()))
    return entries


def write_m3u(path, tracks):
    lines = ['#EXTM3U']
    for name, duration, source in tracks:
        minutes, seconds = duration.split(':')
        title = name.replace('\r', ' ').replace('\n', ' ')
        lines.extend((f'#EXTINF:{int(minutes) * 60 + int(seconds)},{title}', str(Path(source).resolve())))
    Path(path).write_text('\n'.join(lines) + '\n', encoding='utf-8-sig')
