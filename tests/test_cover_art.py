from support import temporary_workspace
import unittest
from pathlib import Path

import mutagen
import numpy as np
import soundfile as sf
from PIL import Image
from mutagen.id3 import TIT2

from cover_art import read_cover, write_cover


class CoverTests(unittest.TestCase):
    def test_embedded_cover_preserves_decoded_audio_and_title(self):
        with temporary_workspace() as folder:
            folder = Path(folder)
            image = folder / 'cover.png'
            Image.new('RGB', (320, 240), 'blue').save(image)
            for extension in ('mp3', 'flac', 'wav'):
                with self.subTest(extension=extension):
                    path = folder / ('song.' + extension)
                    sf.write(path, np.full((8000, 2), .1), 8000)
                    audio = mutagen.File(path)
                    if audio.tags is None:
                        audio.add_tags()
                    if extension == 'flac':
                        audio['title'] = 'original'
                    else:
                        audio.tags.add(TIT2(encoding=3, text=['original']))
                    audio.save()
                    samples, rate = sf.read(path)
                    self.assertIsNone(read_cover(path))
                    write_cover(path, image)
                    self.assertTrue(read_cover(path))
                    updated, updated_rate = sf.read(path)
                    self.assertEqual(rate, updated_rate)
                    np.testing.assert_array_equal(samples, updated)
                    audio = mutagen.File(path)
                    title = audio['title'][0] if extension == 'flac' else audio.tags['TIT2'].text[0]
                    self.assertEqual(title, 'original')
                    write_cover(path, image)
                    self.assertTrue(read_cover(path))


if __name__ == '__main__':
    unittest.main()
