"""Embedded album artwork; update a temporary copy before replacing the file."""
import io
import os
from pathlib import Path
import shutil
import tempfile

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.wave import WAVE
from PIL import Image, ImageOps


def read_cover(path):
    audio = mutagen.File(path)
    if isinstance(audio, FLAC):
        pictures = audio.pictures
    elif isinstance(audio, (MP3, WAVE)):
        pictures = audio.tags.getall('APIC') if audio.tags else []
    elif isinstance(audio, MP4):
        covers = audio.tags.get('covr', []) if audio.tags else []
        return bytes(covers[0]) if covers else None
    else:
        return None
    picture = next((p for p in pictures if p.type == 3), pictures[0] if pictures else None)
    return picture.data if picture else None


def write_cover(path, image_path):
    path = Path(path)
    with Image.open(image_path) as image:
        image = ImageOps.exif_transpose(image).convert('RGB')
        width, height = image.size
        output = io.BytesIO()
        image.save(output, format='JPEG', quality=95)
        data = output.getvalue()
    handle, temporary = tempfile.mkstemp(prefix='.azure-cover-', suffix=path.suffix, dir=path.parent)
    os.close(handle)
    try:
        shutil.copy2(path, temporary)
        audio = mutagen.File(temporary)
        if isinstance(audio, FLAC):
            others = [p for p in audio.pictures if p.type != 3]
            audio.clear_pictures()
            for picture in others:
                audio.add_picture(picture)
            picture = Picture()
            picture.type, picture.mime = 3, 'image/jpeg'
            picture.width, picture.height, picture.depth = width, height, 24
            picture.data = data
            audio.add_picture(picture)
        elif isinstance(audio, (MP3, WAVE)):
            if audio.tags is None:
                audio.add_tags()
            others = [p for p in audio.tags.getall('APIC') if p.type != 3]
            descriptions = {p.desc for p in others}
            description = 'AzureMusicPlayer front cover'
            while description in descriptions:
                description += ' '
            audio.tags.setall('APIC', others + [APIC(encoding=3, mime='image/jpeg',
                                                    type=3, desc=description, data=data)])
        elif isinstance(audio, MP4):
            if audio.tags is None:
                audio.add_tags()
            audio.tags['covr'] = [MP4Cover(data, imageformat=MP4Cover.FORMAT_JPEG)]
        else:
            raise ValueError('此音樂格式尚不支援寫入封面')
        audio.save()
        if read_cover(temporary) != data:
            raise ValueError('封面寫入驗證失敗')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
