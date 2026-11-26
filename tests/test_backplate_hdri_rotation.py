"""A Backplate's HDRI (and any plain environment HDRI) shown as Modo shows it and turned the way Modo turns it, in every
engine and in Modo's viewport.

Modo's spherical projection along Y puts an image's middle (u 0.5) at +Z, u growing toward +X (tools/probe_cl_hdri_compass
.py, a perspective camera in Modo's own render); a Texture Locator's Rotation Y carries +X toward -Z. The engines, handed
a plain image with its locator's matrix, show its middle at -Z, u growing toward +X: what Modo shows mirrored front to
back, measured in MoonRay (vector, XPU), XPU2 (incl. RT/Rhea) and MoonLightIPR. environment_layout lays the file out
(column u showing Modo's 0.5 - u) so that they show what Modo shows. Up to 0.5.6.2 they did not, and a turn of the HDRI
went the other way round."""
import json
import math
import pathlib
import random
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import backplate, backplate_viewport, environment_layout  # noqa: E402

KIT = ROOT / 'kit/MoonRayForModo'


def modo_u(d):
    """Where Modo's spherical projection along Y reads an image for a direction in the locator's space."""
    return (0.5 + math.atan2(d[0], d[2]) / (2 * math.pi)) % 1.0


def engines_u(d):
    """Where the engines read a plain image placed at rest (backplate.latlong_direction's layout)."""
    return (0.5 + math.atan2(d[0], -d[2]) / (2 * math.pi)) % 1.0


def into_locator(matrix, w):
    """A world direction in the space of a turn (rows its axes; the inverse of a turn is its transpose)."""
    return [sum(w[c] * matrix[r * 4 + c] for c in range(3)) for r in range(3)]


def close_u(testcase, a, b, places=6):
    testcase.assertAlmostEqual(min(abs(a - b), 1 - abs(a - b)), 0.0, places=places)


def directions(count=40):
    rng = random.Random(7)
    found = []
    while len(found) < count:
        d = [rng.uniform(-1, 1) for _ in range(3)]
        if 0.1 < math.sqrt(sum(v * v for v in d)) <= 1 and abs(d[0]) + abs(d[2]) > 0.05:
            found.append(d)
    return found


class Turn(unittest.TestCase):
    def test_the_turn_is_modos_rotation_y(self):
        # A positive Rotation Y carries +X toward -Z, as host.world_matrix of a Texture Locator turned so (the probe).
        m = backplate.hdri_matrix(90)
        self.assertEqual([round(v, 6) for v in m[0:3]], [0, 0, -1])
        self.assertEqual([round(v, 6) for v in m[8:11]], [1, 0, 0])
        self.assertEqual(backplate.hdri_matrix(0), backplate.IDENTITY)

    def test_modo_shows_the_middle_at_plus_z(self):
        # What the compass probe found: u 0.5 at +Z, 0.75 at +X, 0.25 at -X, the seam at -Z.
        close_u(self, modo_u([0, 0, 1]), 0.5)
        close_u(self, modo_u([1, 0, 0]), 0.75)
        close_u(self, modo_u([-1, 0, 0]), 0.25)
        close_u(self, modo_u([0, 0, -1]), 0.0)

    def test_the_laid_out_file_shows_what_modo_shows(self):
        # The engines read column engines_u(d) of the laid-out file, which holds Modo's column 0.5 - u.
        for d in directions():
            close_u(self, 0.5 - engines_u(d), modo_u(d))

    def test_the_image_tool_steps(self):
        self.assertEqual(environment_layout.oiiotool_arguments(2048), ['--flop', '--cshift', '+1024+0'])

    def test_latlong_direction_is_the_engines_layout(self):
        width, height = 64, 32
        for x, y in ((0, 5), (17, 16), (40, 30), (63, 1)):
            close_u(self, engines_u(backplate.latlong_direction(x, y, width, height)), (x + .5) / width)


class ReflectionBake(unittest.TestCase):
    """The photo laid over the HDRI (backplate.reflection_environment): the HDRI's columns mirrored (--flop) then moved
    hdri_shift to the right, in the engines' layout, shown at rest: what Modo shows of the HDRI turned by Rotation."""

    def test_the_shift_against_modo(self):
        width = 3600
        for rotation in (0, 30, 90, -45, 200):
            shift = backplate.hdri_shift(rotation, width)
            m = backplate.hdri_matrix(rotation)
            for w in directions(12):
                u = engines_u(w)                          # the baked file's column the engines read for w
                source = (1.0 - u + shift / float(width)) % 1.0    # the HDRI's column there (flop, then shift)
                close_u(self, source, modo_u(into_locator(m, w)), places=3)

    def test_at_rest_half_a_turn_along(self):
        self.assertEqual(backplate.hdri_shift(0, 2048), 1024)
        self.assertEqual(backplate.hdri_shift(90, 2048), 512)
        self.assertEqual(backplate.hdri_shift(-90, 2048), 1536)


class Entries(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.folder.name)
        self.hdri, self.laid = base / 'sky.exr', base / 'laid.exr'
        for path in (self.hdri, self.laid):
            path.write_bytes(b'x')

    def tearDown(self):
        self.folder.cleanup()

    def test_the_backplate_hdri_is_laid_out_and_turned(self):
        entity = {'class': backplate.CLASS, 'identity': 'bp', 'name': 'Backplate', 'matrix': backplate.IDENTITY,
                  'parameters': {'hdri': str(self.hdri), 'hdri_rotation': 90.0, 'hdri_camera': True, 'ground': False}}
        camera = {'matrix': backplate.IDENTITY, 'focal_mm': 50.0, 'film_mm': 36.0}
        with mock.patch('moonray_modo.native.backplate', return_value=True), \
                mock.patch('moonray_modo.native.shadow_catcher_runtime', return_value=False), \
                mock.patch.object(environment_layout, 'image', return_value=self.laid):
            result = backplate.apply({'entities': [entity], 'camera': camera, 'width': 640, 'height': 360}, [])
        sky = [e for e in result['environments'] if e['name'] == 'Backplate HDRI'][0]
        self.assertEqual(sky['path'], str(self.laid))
        self.assertEqual(sky['laid_out_from'], str(self.hdri.resolve()))
        self.assertEqual(sky['matrix'], backplate.hdri_matrix(90.0))
        self.assertTrue(sky['camera'])

    def test_laid_out_leaves_others_and_failures_alone(self):
        stack = {'kind': 'stack', 'layers': []}
        self.assertIs(environment_layout.laid_out(stack), stack)
        image = {'kind': 'image', 'path': str(self.hdri), 'matrix': backplate.IDENTITY}
        with mock.patch.object(environment_layout, 'image', side_effect=ValueError('no tool')):
            self.assertIs(environment_layout.laid_out(image), image)
        with mock.patch.object(environment_layout, 'image', return_value=self.laid) as made:
            once = environment_layout.laid_out(image)
            self.assertEqual(once['path'], str(self.laid))
            self.assertEqual(once['matrix'], image['matrix'])
            # Laid out once only.
            self.assertIs(environment_layout.laid_out(once), once)
            self.assertEqual(made.call_count, 1)

    def test_plain_modo_hdris_are_laid_out(self):
        source = (KIT / 'python/moonray_modo/environments.py').read_text(encoding='utf-8')
        self.assertIn('result.append(laid_out(stack[0]))', source)


class Item:
    def __init__(self, ident, tags=None, **channels):
        self.id, self.values, self.tags = ident, channels, dict(tags or {})

    def channel(self, name):
        if name not in self.values:
            raise LookupError(name)
        return type('C', (), {'get': lambda _, v=self.values[name]: v})()

    def hasTag(self, key):
        return key in self.tags

    def readTag(self, key):
        return self.tags[key]


def plate(**values):
    return Item('bp1', **{'mr_' + k: v for k, v in values.items()})


class Viewport(unittest.TestCase):
    """The HDRI in Modo's viewport: a Modo environment of the kit's own, its image layer's Texture Locator turned by
    HDRI Rotation (the GUI-free part; tools/probe_cl_backplate_hdri_viewport.py checks it in Modo)."""

    def test_none_without_an_hdri_or_switched_off(self):
        self.assertEqual(backplate_viewport.want_hdri(plate(hdri='')), '')
        self.assertEqual(backplate_viewport.want_hdri(plate(hdri='C:/sky.exr', viewport_hdri=False)), '')

    def test_the_hdri_and_its_rotation(self):
        setup = json.loads(backplate_viewport.want_hdri(plate(hdri='C:/Skies/Sky.EXR', hdri_rotation=37.5)))
        self.assertEqual(setup, {'hdri': 'c:/skies/sky.exr', 'path': 'C:/Skies/Sky.EXR', 'rotation': 37.5})
        # Its rotation at 0 where left alone.
        self.assertEqual(json.loads(backplate_viewport.want_hdri(plate(hdri='C:/a.exr')))['rotation'], 0.0)

    def test_a_turn_sets_it_up_again(self):
        before = backplate_viewport.want_hdri(plate(hdri='C:/a.exr', hdri_rotation=0.0))
        after = backplate_viewport.want_hdri(plate(hdri='C:/a.exr', hdri_rotation=90.0))
        self.assertEqual(backplate_viewport.plan({'bp1': after}, [('env1', 'bp1', before)]), ([], [], [('env1', after)]))
        self.assertEqual(backplate_viewport.plan({'bp1': after}, [('env1', 'bp1', after)]), ([], [], []))
        self.assertEqual(backplate_viewport.plan({'bp1': ''}, [('env1', 'bp1', after)]), (['env1'], [], []))

    def test_it_is_never_rendered(self):
        self.assertTrue(backplate_viewport.viewport_only(Item('env1', tags={backplate_viewport.OWNER: 'bp1'})))
        self.assertFalse(backplate_viewport.viewport_only(Item('env0')))
        source = (KIT / 'python/moonray_modo/environments.py').read_text(encoding='utf-8')
        self.assertIn('if not render_visible(environment) or viewport_only(environment):', source)

    def test_its_layer_is_turned_as_the_renders_turn_the_hdri(self):
        module = (KIT / 'python/moonray_modo/backplate_viewport.py').read_text(encoding='utf-8')
        for line in ("'!item.channel txtrLocator$projType spherical'", "'!item.channel txtrLocator$projAxis 1'",
                     "'!transform.channel rot.Y %s' % setup['rotation']", "'!item.channel imageMap$effect envColor'"):
            self.assertIn(line, module)

    def test_the_option_and_its_listeners(self):
        catalog = json.loads((KIT / 'python/moonray_modo/entity_catalog.json').read_text(encoding='utf-8'))

        def find(node):
            if isinstance(node, dict):
                if 'BackplateEnvironment' in node and 'attributes' in node['BackplateEnvironment']:
                    return node['BackplateEnvironment']
                for value in node.values():
                    found = find(value)
                    if found:
                        return found
        spec = find(catalog)['attributes']['viewport_hdri']
        self.assertEqual((spec['type'], spec['default'], spec['group'], spec['label']), ('Bool', True, 'HDRI', 'HDRI in the viewport'))
        self.assertIn('mr_viewport_hdri', (KIT / 'entities.cfg').read_text(encoding='utf-8'))
        for key in ('hdri', 'hdri_rotation', 'viewport_hdri'):
            self.assertIn(key, backplate_viewport.PLATE_KEYS)


if __name__ == '__main__':
    unittest.main()
