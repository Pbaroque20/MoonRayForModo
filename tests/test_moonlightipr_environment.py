"""MoonLightIPR's environment image as MoonRay is given it: a plain HDRI turned half a turn about the vertical in its
own space (environments.emit), a baked stack not; and textures larger than the limit fitted with their shape kept."""
import pathlib
import struct
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import moonlightipr_materials, moonlightipr_scene  # noqa: E402

IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def axes(item):
    """The image axes MoonLightIPR is sent for one environment, as nine numbers."""
    with patch.object(moonlightipr_scene, 'environment_image', return_value='env.pfm'):
        parts = moonlightipr_scene.environment_section({'environments': [item]}, 0.0, [], None)
    record = parts[3]
    return [round(v, 6) for v in struct.unpack('<10f', record[-40:])[1:]]


class EnvironmentTurn(unittest.TestCase):
    def test_a_plain_image_is_turned_as_moonray_is_given_it(self):
        plain = {'kind': 'image', 'intensity': 1.0, 'path': 'a.exr', 'matrix': IDENTITY}
        self.assertEqual(axes(plain), [-1, 0, 0, 0, 1, 0, 0, 0, -1])

    def test_a_turned_image_keeps_its_turn_beneath_the_half_turn(self):
        quarter = [0, 0, -1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 1]
        self.assertEqual(axes({'kind': 'image', 'intensity': 1.0, 'path': 'a.exr', 'matrix': quarter}), [0, 0, 1, 0, 1, 0, -1, 0, 0])

    def test_a_baked_stack_is_not_turned(self):
        stack = {'kind': 'stack', 'intensity': 1.0, 'matrix': IDENTITY, 'layers': []}
        self.assertEqual(axes(stack), [1, 0, 0, 0, 1, 0, 0, 0, 1])


class TextureFit(unittest.TestCase):
    def test_the_shape_is_kept(self):
        self.assertEqual(moonlightipr_materials.fitted(2103, 1673), (1024, 815))
        self.assertEqual(moonlightipr_materials.fitted(512, 4096), (128, 1024))
        self.assertEqual(moonlightipr_materials.fitted(4096, 4096), (1024, 1024))

    def test_a_larger_image_is_resized_not_padded(self):
        compiler = moonlightipr_materials.Compiler()
        commands = []

        def run(args, name):
            commands.append(args)
            return '2103 x 1673, 4 channel' if args[0] == '--info' else ''
        with patch.object(compiler, 'run', side_effect=run), patch('pathlib.Path.replace'), patch('pathlib.Path.mkdir'):
            compiler.convert(pathlib.Path('label.png'), pathlib.Path('label.tga'), False)
        written = commands[-1]
        self.assertNotIn('--fit', written)
        self.assertEqual(written[written.index('--resize') + 1], '1024x815')


if __name__ == '__main__':
    unittest.main()
