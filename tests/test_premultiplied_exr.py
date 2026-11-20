"""A render's OpenEXR with alpha written premultiplied, as the type is read (After Effects, Nuke): the environment seen
past every surface taken out of the beauty's colour, every other channel, part and data type kept (MoonRay Source
Override "Premultiplied OpenEXR alpha", image_formats.take_out_environment). Over a visible grey sky MoonRay's and
XPU2's soft edges held the sky (red over alpha 7.5 where the surface is 2.2) and After Effects showed a halo; the render
check is tools/check_alpha_edges.py."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import composite_output, image_formats, native

SKY = list(image_formats.BACKGROUND)


def part(*names, kind='float'):
    return [(name, kind) for name in names]


class Layout(unittest.TestCase):
    def test_one_type_for_every_channel(self):
        info = ('render.exr :  160 x  120, 7 channel, float openexr\n'
                '    channel list: R, G, B, A, environment_background.R, environment_background.G, environment_background.B\n'
                '    compression: "zip"\n')
        self.assertEqual(composite_output.layout(info), [part('R', 'G', 'B', 'A', *SKY)])

    def test_each_channels_type_where_they_differ(self):
        # The names came back as "R (half)" here, so a 16-bit render with a Cryptomatte had no channel found by its name.
        info = ('render.exr :  160 x  120, 5 channel, half/half/half/half/float openexr\n'
                '    channel list: R (half), G (half), B (half), A (half), CryptoObject00.R (float)\n')
        self.assertEqual(composite_output.layout(info), [part('R', 'G', 'B', 'A', kind='half') + [('CryptoObject00.R', 'float')]])

    def test_each_part_of_a_multipart_file(self):
        info = ('render.exr :  160 x  120, 4 channel, half openexr\n'
                '    2 subimages: 160x120 [h,h,h,h], 160x120 [f]\n'
                ' subimage  0:  160 x  120, 4 channel, half openexr\n'
                '    channel list: R, G, B, A\n'
                ' subimage  1:  160 x  120, 1 channel, float openexr\n'
                '    channel list: depth.Z\n')
        self.assertEqual(composite_output.layout(info), [part('R', 'G', 'B', 'A', kind='half'), part('depth.Z')])


class WithoutEnvironment(unittest.TestCase):
    def test_the_beauty_less_its_environment_background_the_rest_kept(self):
        parts = [part('R', 'G', 'B', 'A', kind='half') + part('CryptoObject00.R') + part(*SKY, kind='half')]
        args = image_formats.without_environment(parts, 'render.exr', 'out.exr')
        self.assertEqual(args[0], '--no-autopremult')
        taken_out = args.index('--sub')
        self.assertEqual(args[taken_out - 7:taken_out], ['render.exr', '--subimage', '0', '--ch', ','.join(SKY), '--chnames', 'R,G,B'])
        self.assertEqual(args[taken_out + 1], '--clamp:min=0')
        # Every other channel appended, then put back in the file's order.
        self.assertIn('A,CryptoObject00.R,' + ','.join(SKY), args)
        self.assertEqual(args[args.index('--chappend') + 1:args.index('--chappend') + 3], ['--ch', 'R,G,B,A,CryptoObject00.R,' + ','.join(SKY)])
        # Each channel written in its own type: worked out, the colour would be 32-bit.
        self.assertIn('R=half', args)
        self.assertIn('CryptoObject00.R=float', args)
        self.assertEqual(args[-2:], ['-o', 'out.exr'])

    def test_a_copy_without_the_channels_takes_them_from_the_render(self):
        args = image_formats.without_environment([part('R', 'G', 'B', 'A')], 'denoised.exr', 'out.exr', ('render.exr', 0, ','.join(SKY)))
        taken_out = args.index('--sub')
        self.assertEqual(args[taken_out - 7:taken_out - 2], ['render.exr', '--subimage', '0', '--ch', ','.join(SKY)])

    def test_nothing_to_do_without_alpha_or_environment(self):
        self.assertIsNone(image_formats.without_environment([part('R', 'G', 'B', *SKY)], 'a.exr', 'b.exr'))
        self.assertIsNone(image_formats.without_environment([part('R', 'G', 'B', 'A')], 'a.exr', 'b.exr'))

    def test_other_parts_are_kept_as_they_are(self):
        parts = [part('R', 'G', 'B', 'A', *SKY), part('depth.Z')]
        args = image_formats.without_environment(parts, 'render.exr', 'out.exr')
        self.assertEqual(args[args.index('--siappend') - 3:args.index('--siappend')], ['render.exr', '--subimage', '1'])

    def test_the_switch_leaves_the_file_alone_when_off(self):
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_PREMULTIPLIED_EXR': '0'}), \
                mock.patch('moonray_modo.composite_output.channel_layout', side_effect=AssertionError('read')):
            self.assertFalse(native.premultiplied_exr())
            self.assertFalse(image_formats.take_out_environment('runtime', 'render.exr'))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('MOONRAY_MODO_PREMULTIPLIED_EXR', None)
            self.assertTrue(native.premultiplied_exr())


class Wired(unittest.TestCase):
    def test_renders_and_the_preview_windows_save_take_it_out(self):
        render = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/render.py').read_text(encoding='utf-8')
        # After the preview has had its copy (_show_output), so the sky stays in what it shows.
        self.assertLess(render.index('self._show_output(destination)'), render.index('take_out_environment(runtime,destination)'))
        self.assertIn('take_out_environment(runtime,denoised,sky)', render)
        tools = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/panel_tools.py').read_text(encoding='utf-8')
        self.assertIn('self._premultiplied(frame, source, written)', tools)
        self.assertIn("self._premultiplied(frame, frame['files']['beauty'], written)", tools)
        prefs = (ROOT / 'kit/MoonRayForModo/preferences.cfg').read_text(encoding='utf-8')
        self.assertIn('cmd moonray.pref.premultipliedExr ?', prefs)
        self.assertIn("'premultiplied_exr': (True, bool)", (ROOT / 'kit/MoonRayForModo/python/moonray_modo/preferences.py').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
