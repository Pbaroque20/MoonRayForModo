"""A Modo light's Shader Tree images as the kit draws them (light_images): where Modo looks a light's image up (the
light's own point, through the Texture Locator), the colour of a light without a size, the picture laid across an area
light (mirrored across, as MoonRay lays a RectLight's texture), and what MoonRay is given for it. No Modo or renderer
launch: images are made here as pixel lists."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
for _name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(_name, types.ModuleType(_name))
from moonray_modo import light_images as images  # noqa: E402

IDENTITY = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]
SIZE = 16


def code_image(size=SIZE):
    """tools/make_uv_code_image.py's picture: red is u, green is v, blue 0.25; rows bottom up as sample reads them."""
    pixels = []
    for row in range(size):
        for column in range(size):
            pixels += [(column + .5) / size, (row + .5) / size, .25]
    return pixels, None, size, size


def layer(projType='none', axis=2, matrix=IDENTITY, **extra):
    held = {'name': 'layer', 'path': 'C:/images/code.exr', 'srgb': False, 'color_space': '', 'opacity': 1.0, 'blend': 'normal',
            'invert': False, 'alpha': 'use', 'projection': images.projection({'projType': projType, 'projAxis': axis}, matrix)}
    held.update(extra)
    return held


def at(found, s, t, base=(1.0, 1.0, 1.0), image=None):
    return images.layered(list(base), [found], [image or code_image()], images.point_of(s, t))


class Projection(unittest.TestCase):
    def test_solid_is_laid_as_planar_along_y_the_image_middle_row_across(self):
        found = layer('none')
        self.assertEqual(found['projection']['projection'], 'planar')
        self.assertEqual(found['projection']['axis'], 1)
        u, v, b = at(found, .25, .9)
        self.assertAlmostEqual(u, .25, places=2)
        self.assertAlmostEqual(v, .5, places=2)

    def test_planar_along_z_lays_the_image_once_across_and_up(self):
        u, v, _ = at(layer('planar', 2), .2, .8)
        self.assertAlmostEqual(u, .2, places=2)
        self.assertAlmostEqual(v, .8, places=2)

    def test_the_locators_place_moves_the_image_on_the_light(self):
        moved = list(IDENTITY)
        moved[12:15] = [.25, .1, 0.0]
        u, v, _ = at(layer('planar', 2, moved), .5, .5)
        self.assertAlmostEqual(u, .25, places=2)
        self.assertAlmostEqual(v, .4, places=2)

    def test_uv_front_and_implicit_give_one_colour(self):
        for kind in ('uv', 'front', 'implicitUV'):
            self.assertEqual(at(layer(kind), .1, .1), at(layer(kind), .9, .7))

    def test_opacity_and_blend_over_the_lights_colour(self):
        red = (1.0, 0.0, 0.0)
        half = at(layer('planar', 2, opacity=.5), .5, .5, red)
        self.assertEqual([round(c, 3) for c in half], [.75, .25, .125])
        times = at(layer('planar', 2, blend='multiply'), .5, .5, red)
        self.assertEqual([round(c, 3) for c in times], [.5, 0.0, 0.0])


class Picture(unittest.TestCase):
    def test_the_bakes_size_follows_what_changes(self):
        self.assertEqual(images.bake_size([layer('none')]), (images.ROW_SIZE, 1))
        self.assertEqual(images.bake_size([layer('planar', 2)]), (images.BAKE_SIZE, images.BAKE_SIZE))
        self.assertEqual(images.bake_size([layer('uv')]), (1, 1))

    def test_the_picture_is_mirrored_across_and_top_row_first(self):
        values = images.bake([1, 1, 1], [layer('planar', 2)], [code_image()], 4, 4)
        first, last = values[0:3], values[-3:]
        # Top left of the picture: the light's right (+X, u near 1) at its top (+Y, v near 1).
        self.assertGreater(first[0], .7)
        self.assertGreater(first[1], .7)
        self.assertLess(last[0], .3)
        self.assertLess(last[1], .3)

    def test_plain_only_for_one_opaque_layer_laid_once(self):
        self.assertTrue(images.plain([layer('planar', 2)], False))
        self.assertFalse(images.plain([layer('planar', 2)], True))
        self.assertFalse(images.plain([layer('none')], False))
        self.assertFalse(images.plain([layer('planar', 2, opacity=.5)], False))
        self.assertFalse(images.plain([layer('planar', 2), layer('planar', 2)], False))
        moved = list(IDENTITY)
        moved[12] = .1
        self.assertFalse(images.plain([layer('planar', 2, moved)], False))


class Apply(unittest.TestCase):
    def apply(self, kind, layers, warnings=None):
        light = {'kind': kind, 'name': 'L', 'color': [1.0, 0.0, 0.0]}
        folder = Path(tempfile.mkdtemp())
        written = []

        def write(target, values, width, height):
            written.append((width, height))
            Path(target).write_text('x')
        with mock.patch.object(images, '_image', lambda l: code_image()), mock.patch.object(images, 'write_picture', write), \
                mock.patch.object(images, 'mirrored', lambda l: 'C:/cache/mirrored.exr'), \
                mock.patch('moonray_modo.textures.cache_root', lambda: folder), \
                mock.patch('moonray_modo.textures.asset_path', lambda p: folder / 'code.exr'):
            (folder / 'code.exr').write_text('x')
            images.apply(light, layers, warnings if warnings is not None else [])
        return light, written

    def test_a_light_without_a_size_takes_the_images_colour_at_its_middle(self):
        for kind in ('SpotLight', 'SphereLight', 'DistantLight'):
            light, written = self.apply(kind, [layer('none')])
            self.assertEqual([round(c, 3) for c in light['color']], [.5, .5, .25])
            self.assertNotIn('texture', light)
            self.assertEqual(written, [])

    def test_an_area_light_is_given_a_picture_and_white(self):
        light, written = self.apply('RectLight', [layer('none')])
        self.assertTrue(light['texture'].endswith('.exr'))
        self.assertEqual(light['color'], [1.0, 1.0, 1.0])
        self.assertEqual(written, [(images.ROW_SIZE, 1)])
        light, written = self.apply('RectLight', [layer('planar', 2)])
        self.assertEqual(light['texture'], 'C:/cache/mirrored.exr')
        self.assertEqual(written, [])

    def test_one_colour_across_an_area_light_is_its_colour_not_a_one_pixel_picture(self):
        light, written = self.apply('RectLight', [layer('uv')])
        self.assertNotIn('texture', light)
        self.assertEqual(written, [])

    def test_a_mesh_light_says_its_image_is_not_drawn(self):
        warnings = []
        light, _ = self.apply('MeshLight', [layer('none')], warnings)
        self.assertEqual(light['color'], [1.0, 0.0, 0.0])
        self.assertIn('not drawn', warnings[0])


class Emit(unittest.TestCase):
    def test_moonray_is_given_the_lights_texture(self):
        try:
            from moonray_modo import lighting
        except ImportError as exc:
            self.skipTest('lighting needs Modo here: %s' % exc)
        scene = {'lights': [{'kind': 'RectLight', 'identity': 'area', 'name': 'Area', 'matrix': IDENTITY, 'color': [1, 1, 1], 'intensity': 1.0,
                             'width': 2.0, 'height': 1.0, 'texture': 'C:\\cache\\Light Images\\a.exr'}], 'production': {'lights': {}}}
        lines = []
        try:
            lighting.emit(scene, [], 0, lines)
        except (ImportError, AttributeError) as exc:
            self.skipTest('lighting needs Modo here: %s' % exc)
        self.assertIn('  ["texture"] = "C:/cache/Light Images/a.exr",', lines)


if __name__ == '__main__':
    unittest.main()
