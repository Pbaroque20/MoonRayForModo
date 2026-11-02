"""The beauty saved with the render's alpha, and outputs saved as one multilayer OpenEXR: the image tool's arguments."""
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import image_formats


class Alpha(unittest.TestCase):
    def test_a_preview_beauty_takes_its_alpha_from_the_alpha_output(self):
        args = image_formats.with_alpha('png8', 'beauty.exr', 'out.png', {}, alpha=('alpha.exr', 'R'))
        self.assertEqual(args[:9], ['--no-autopremult', 'beauty.exr', '--fixnan', 'black', '--ch', '0,1,2', '--chnames', 'R,G,B', 'alpha.exr'])
        # Taken in twice: to divide the colour by, and kept beside it.
        self.assertEqual(args.count('alpha.exr'), 2)
        self.assertIn('--unpremult', args)
        self.assertEqual(args[-5:], ['--attrib:type=int', 'oiio:UnassociatedAlpha', '1', '-o', 'out.png'])

    def test_the_renders_own_file_is_read_as_before(self):
        args = image_formats.with_alpha('tif16', 'render.exr', 'out.tif')
        self.assertEqual(args[:6], ['--no-autopremult', 'render.exr', '--fixnan', 'black', '--ch', 'R,G,B,A'])
        self.assertIn('render.exr', args[6:])

    def test_an_exr_beauty_gets_an_a_channel(self):
        args = image_formats.exr_with_alpha('exr16', 'beauty.exr', ('alpha.exr', 'R'), 'out.exr')
        self.assertEqual(args, ['beauty.exr', '--ch', '0,1,2', '--chnames', 'R,G,B', 'alpha.exr', '--ch', 'R', '--chnames', 'A', '--chappend',
                                '-d', 'half', '-o', 'out.exr'])


class Multilayer(unittest.TestCase):
    def test_layers_are_named_and_a_cryptomatte_stays_float(self):
        self.assertEqual(image_formats.layer_names('beauty', ['R', 'G', 'B'], True), ['R', 'G', 'B'])
        self.assertEqual(image_formats.layer_names('albedo', ['R', 'G', 'B']), ['albedo.R', 'albedo.G', 'albedo.B'])
        layers = [('beauty.exr', ['R', 'G', 'B'], ['R', 'G', 'B'], False), ('alpha.exr', ['R'], ['A'], False),
                  ('crypto.exr', ['CryptoObject00.R'], ['CryptoObject00.R'], True)]
        args = image_formats.multilayer('exr16', layers, 'render.exr')
        self.assertEqual(args.count('--chappend'), 2)
        self.assertEqual(args[-6:], ['-d', 'half', '-d', 'CryptoObject00.R=float', '-o', 'render.exr'])

    def test_a_name_written_twice_is_told_apart(self):
        layers = [('a.exr', ['R'], ['x.R'], False), ('b.exr', ['R'], ['x.R'], False)]
        args = image_formats.multilayer('exr32', layers, 'out.exr')
        self.assertIn('b.x.R', args)


class Dialog(unittest.TestCase):
    def test_a_group_box_ticks_by_its_own_state_and_the_option_is_kept(self):
        source = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/export_dialog.py').read_text(encoding='utf-8')
        self.assertIn('whole.clicked.connect(partial(self.tick_group, group))', source)
        self.assertIn("'output/aov_multilayer'", source)
        tools = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/panel_tools.py').read_text(encoding='utf-8')
        self.assertIn('self.write_layered(', tools)
        self.assertIn("self.write_buffer(frame, key, Path(path), 'png8')", tools)


if __name__ == '__main__':
    unittest.main()
