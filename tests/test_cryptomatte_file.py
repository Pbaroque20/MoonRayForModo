"""Cryptomatte in its own EXR beside the picture (rdla, cryptomatte.own_file_wanted): asked for in Output Renders, or
whenever the picture's compression is lossy, which changes a Cryptomatte's exact IDs (a tester's DWAB frame of 12
objects held 1,162 different IDs, and Photoshop offered 1,530 mattes). The Cryptomatte file is lossless and has the
manifest; the picture keeps its compression and has none. Checkpoints keep it in the picture."""
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import rdla  # noqa: E402

CRYPTO = {'name': 'crypto_object', 'kind': 'cryptomatte', 'category': 'object', 'depth': 6, 'precision': 0, 'filter': 0,
          'part': '', 'expression': ''}


def scene(**exr):
    return {'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1, 5, 1], 'focal_mm': 50.0, 'film_mm': 36.0},
            'materials': {'': {'color': [.5, .5, .5]}},
            'meshes': [{'name': 'Box', 'identity': 'box', 'vertices': [[-1, 0, -1], [1, 0, -1], [1, 0, 1], [-1, 0, 1]], 'faces': [[0, 3, 2, 1]],
                        'material': ''}],
            'lights': [], 'environments': [], 'custom_aovs': [dict(CRYPTO)], 'exr': dict({'compression': 1}, **exr)}


def outputs(text):
    """{output name: (file, compression, metadata)}"""
    found = {}
    for name, body in re.findall(r'RenderOutput\("/modo/aov/([^"]+)"\) \{(.*?)\n\}', text, re.S):
        file = re.search(r'\["file_name"\] = "([^"]+)"', body).group(1)
        compression = re.search(r'\["compression"\] = (\d+)', body).group(1)
        metadata = re.search(r'Metadata\("([^"]+)"\)', body).group(1)
        found[name] = (file, int(compression), metadata)
    return found


def manifest_in(text, path):
    block = re.search(r'Metadata\("%s"\) (.*)' % re.escape(path), text)
    return block is not None and 'cryptomatte/' in block.group(1)


class CryptomatteFile(unittest.TestCase):
    def test_lossless_and_not_asked_it_stays_in_the_picture(self):
        text = rdla.scene_text(scene(), 64, 36, 1, 0.0, r'C:\renders\shot.0030.exr')
        files = {v[0] for v in outputs(text).values()}
        self.assertEqual(files, {r'C:\\renders\\shot.0030.exr'})
        self.assertTrue(manifest_in(text, '/modo/outputMetadata'))

    def test_a_lossy_picture_sends_it_to_its_own_lossless_file(self):
        text = rdla.scene_text(scene(compression=9), 64, 36, 1, 0.0, r'C:\renders\shot.0030.exr')
        got = outputs(text)
        self.assertEqual(got['beauty'][:2], (r'C:\\renders\\shot.0030.exr', 9))
        for name in ('crypto_object', 'object_id'):
            self.assertEqual(got[name][:2], (r'C:\\renders\\shot.cryptomatte.0030.exr', 1), name)
            self.assertEqual(got[name][2], '/modo/outputMetadata/object')
        # The picture's header has no manifest; the Cryptomatte file's has.
        self.assertFalse(manifest_in(text, '/modo/outputMetadata'))
        self.assertTrue(manifest_in(text, '/modo/outputMetadata/object'))

    def test_asked_for_it_goes_to_its_own_file_with_any_compression(self):
        got = outputs(rdla.scene_text(scene(cryptomatte_file=True), 64, 36, 1, 0.0, r'C:\renders\still.exr'))
        self.assertEqual(got['crypto_object'][0], r'C:\\renders\\still.cryptomatte.exr')
        self.assertEqual(got['beauty'][0], r'C:\\renders\\still.exr')

    def test_checkpoints_keep_it_in_the_picture(self):
        value = scene(cryptomatte_file=True)
        value['_recovery'] = {'file': 'C:/renders/still.recovery/checkpoint.exr', 'guides': {}, 'resume': False, 'minutes': 1.0}
        got = outputs(rdla.scene_text(value, 64, 36, 1, 0.0, r'C:\renders\still.exr'))
        self.assertEqual(got['crypto_object'][0], r'C:\\renders\\still.exr')
        self.assertTrue(any('stays in the render' in w for w in value.get('warnings', [])))


if __name__ == '__main__':
    unittest.main()
