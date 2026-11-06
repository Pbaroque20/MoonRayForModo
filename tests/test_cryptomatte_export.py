"""A Cryptomatte saved by Export AOVs: its channels under a layer of its category's own name, the channels MoonRay keeps
only for resuming left out, and the standard header every reader needs (Photoshop's through ProEXR or Exr-IO, Nuke,
Fusion), written word for word: the image tool would otherwise work out the manifest's braces. No Modo launch."""
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import cryptomatte, image_formats  # noqa: E402

CHANNELS = ['CryptoS00.R', 'CryptoS00.G', 'Cryptomatte00.R', 'Cryptomatte00.G', 'Cryptomatte00.B', 'Cryptomatte00.A',
            'Cryptomatte01.R']


class CryptomatteExportTests(unittest.TestCase):
    def test_layer_named_by_category(self):
        self.assertEqual(cryptomatte.export_name('material'), 'CryptoMaterial')
        self.assertEqual(cryptomatte.export_name('object'), 'CryptoObject')
        self.assertEqual(cryptomatte.export_channels(CHANNELS, 'CryptoMaterial'),
                         [('CryptoMaterial00.R', 'Cryptomatte00.R'), ('CryptoMaterial00.G', 'Cryptomatte00.G'),
                          ('CryptoMaterial00.B', 'Cryptomatte00.B'), ('CryptoMaterial00.A', 'Cryptomatte00.A'),
                          ('CryptoMaterial01.R', 'Cryptomatte01.R')])

    def test_header_is_the_standard_one(self):
        held = dict(cryptomatte.header('CryptoMaterial', {'Red [red]': '5255fbee'}))
        prefix = 'cryptomatte/%s/' % ('%08x' % cryptomatte.hash32('CryptoMaterial'))[:7]
        self.assertEqual(held[prefix + 'name'], 'CryptoMaterial')
        self.assertEqual(held[prefix + 'hash'], 'MurmurHash3_32')
        self.assertEqual(held[prefix + 'conversion'], 'uint32_to_float32')
        self.assertEqual(json.loads(held[prefix + 'manifest']), {'Red [red]': '5255fbee'})

    def test_render_header_unchanged(self):
        lines = []
        cryptomatte.metadata([], lines, True, {'custom_aovs': [{'kind': 'cryptomatte', 'category': 'object'}]})
        self.assertIn('cryptomatte/%s/name' % ('%08x' % cryptomatte.hash32('Cryptomatte'))[:7], lines[0])
        self.assertIn('"Cryptomatte"', lines[0])

    def test_arguments_write_the_header_word_for_word(self):
        header = cryptomatte.header('CryptoMaterial', {'A': '00000001', 'B': '00000002'})
        args = image_formats.cryptomatte('in.exr', cryptomatte.export_channels(CHANNELS, 'CryptoMaterial'), header, 'out.exr')
        self.assertEqual(args[:3], ['in.exr', '--ch', 'CryptoMaterial00.R=Cryptomatte00.R,CryptoMaterial00.G=Cryptomatte00.G,'
                                    'CryptoMaterial00.B=Cryptomatte00.B,CryptoMaterial00.A=Cryptomatte00.A,CryptoMaterial01.R=Cryptomatte01.R'])
        evaloff, evalon = args.index('--evaloff'), args.index('--evalon')
        manifest = next(value for key, value in header if key.endswith('manifest'))
        self.assertTrue(evaloff < args.index(manifest) < evalon)
        self.assertEqual(args[-4:], ['-d', 'float', '-o', 'out.exr'])

    def test_only_openexr(self):
        with self.assertRaises(ValueError):
            image_formats.cryptomatte('in.exr', [('CryptoObject00.R', 'Cryptomatte00.R')], [], 'out.png')

    def test_multilayer_carries_headers(self):
        header = cryptomatte.header('CryptoObject', {'A': '00000001'})
        args = image_formats.multilayer('exr32', [('in.exr', ['Cryptomatte00.R'], ['CryptoObject00.R'], True)], 'out.exr', header)
        self.assertIn('--evaloff', args)
        self.assertEqual(args[-2:], ['-o', 'out.exr'])


if __name__ == '__main__':
    unittest.main()
