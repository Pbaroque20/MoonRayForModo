"""Environment images and procedurals under every one of Modo's Texture Locator projections (environment_projections.py,
the Source Override "Environment images in every projection"): the coordinates Modo's own renders looked each direction
up at (fixtures/environment_projections_modo.json, read from tools/probe_cl_environment_projections.py's renders of an
image whose colour is its coordinates), the refusal kept with the switch off, the bake's native copy laying the same map
as Python, and the preference's wiring."""
import array
import ctypes
import json
import math
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
KIT = ROOT / 'kit/MoonRayForModo'
sys.path.insert(0, str(KIT / 'python'))
from moonray_modo import environment_layers, environment_projections as ep, environments, native, procedurals  # noqa: E402

IDENTITY = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def captured(projection, axis=1, matrix=IDENTITY, procedural=False, **channels):
    values = {'projType': projection, 'projAxis': axis, 'wrapU': 1.0, 'wrapV': 1.0, 'uvRotation': 0.0, 'tileU': 'repeat',
              'tileV': 'repeat', 'triplanarBlending': 0.0}
    values.update(channels)
    return ep.capture(None, lambda item, key, default=None: values.get(key, default), matrix, procedural)


def looked_up(projection, d):
    """The image coordinate (u, v), repeat modes applied, weighted over Triplanar's three; None where reset."""
    u = v = 0.0
    for a, b, weight in ep.coordinates(projection, d):
        a, b = ep.tiled(a, projection['tiles'][0]), ep.tiled(b, projection['tiles'][1])
        if a is None or b is None:
            return None
        u, v = u + a * weight, v + b * weight
    return u, v


def apart(a, b):
    d = abs(a - b) % 1.0
    return min(d, 1 - d)


class ModoCoordinates(unittest.TestCase):
    def test_each_projection_looks_up_where_modo_does(self):
        cases = json.loads((ROOT / 'tests/fixtures/environment_projections_modo.json').read_text())
        for name, case in cases.items():
            projection = captured(case['locator']['projType'], case['locator']['projAxis'], case['matrix'],
                                  **{k: (float(v) if k not in ('projType', 'tileU', 'tileV') else v) for k, v in case['locator'].items()
                                     if k not in ('projType', 'projAxis')})
            for x, y, z, red, green, blue in case['samples']:
                found = looked_up(projection, (x, y, z))
                if blue < .1:
                    self.assertIsNone(found, name)   # reset: nothing of the image there
                    continue
                self.assertIsNotNone(found, name)
                # Modo's filtered picture against the exact coordinate: within a few pixels of the 512 x 256 image (its
                # filter reaches furthest at an Edge-repeated border).
                self.assertLess(apart(found[0], red), .016, '%s u at %s' % (name, (x, y, z)))
                self.assertLess(apart(found[1], green), .016, '%s v at %s' % (name, (x, y, z)))

    def test_plain_cases(self):
        # Planar along Y: across x, up the image along z; the locator's size divides.
        self.assertEqual(looked_up(captured('planar'), (.3, .8, .2)), (.8, .7))
        sized = captured('planar', matrix=[2.0, 0, 0, 0, 0, 2.0, 0, 0, 0, 0, 2.0, 0, 0, 0, 0, 1])
        self.assertAlmostEqual(looked_up(sized, (.4, .8, .2))[0], .7)
        # The locator's position does nothing to a direction.
        moved = captured('planar', matrix=IDENTITY[:12] + [5.0, 1.0, -3.0, 1.0])
        self.assertEqual(looked_up(moved, (.3, .8, .2)), (.8, .7))
        # Cubic: seen from inside, +Z's face runs the other way from -Z's.
        self.assertAlmostEqual(looked_up(captured('cubic'), (.2, .1, .9))[0], .3)
        self.assertAlmostEqual(looked_up(captured('cubic'), (.2, .1, -.9))[0], .7)
        # Solid lays an image as Cubic does; it has nothing to lay a procedural by.
        self.assertEqual(captured('none')['projection'], 'cubic')
        with self.assertRaises(ValueError):
            captured('none', procedural=True)
        # UV Map, Implicit UV and Front Projection have no coordinates in an environment: the image at (0, 0).
        for kind in ('uv', 'implicitUV', 'front'):
            self.assertEqual(ep.coordinates(captured(kind), (.3, .4, .5)), [(0.0, 0.0, 1.0)])
        # Light Probe: an angular map looking along -Z (axis Y), the opposite way at its rim.
        self.assertEqual(looked_up(captured('lightprobe'), (0, 0, -1)), (.5, .5))
        self.assertAlmostEqual(looked_up(captured('lightprobe'), (1, 0, 0))[0], .25)
        # Triplanar weights: hard where one axis is well ahead of the others.
        weights = [w for *_, w in ep.coordinates(captured('triplanar'), (.1, .2, .97))]
        self.assertEqual(len(weights), 1)
        weights = [w for *_, w in ep.coordinates(captured('triplanar'), (.6, .0, .8))]
        self.assertAlmostEqual(sum(weights), 1.0)

    def test_repeat_modes(self):
        self.assertAlmostEqual(ep.tiled(1.25, 'repeat'), .25)
        self.assertAlmostEqual(ep.tiled(1.25, 'mirror'), .75)
        self.assertAlmostEqual(ep.tiled(-.25, 'mirror'), .25)
        self.assertEqual(ep.tiled(1.25, 'edge'), 1.0)
        self.assertIsNone(ep.tiled(1.25, 'reset'))
        self.assertEqual([ep.texel(i, 4, 'mirror') for i in (-1, 4, 5)], [0, 3, 2])

    def test_spherical_along_y_stays_the_plain_image(self):
        self.assertFalse(ep.wanted('spherical', 1, IDENTITY))
        self.assertFalse(ep.wanted('spherical', 'y', [2.0, 0, 0, 0, 0, 2.0, 0, 0, 0, 0, 2.0, 0, 0, 0, 0, 1]))
        self.assertTrue(ep.wanted('spherical', 0))
        self.assertTrue(ep.wanted('spherical', 1, [2.0, 0, 0, 0, 0, .5, 0, 0, 0, 0, 1.5, 0, 0, 0, 0, 1]))
        for kind in ('planar', 'cylindrical', 'cubic', 'box', 'front', 'uv', 'lightprobe', 'implicitUV', 'triplanar', 'none'):
            self.assertTrue(ep.wanted(kind, 1), kind)


def pattern(kind, layer, **colours):
    """A Grid's or Dots' settings (procedurals.capture's) from the layer channels a fixture case holds."""
    return dict({'kind': kind, 'pattern': layer['type'], 'width': float(layer.get('lineWidth', layer.get('dotWidth'))),
                 'transition': float(layer['transWidth']), 'bias': float(layer['bias']), 'gain': float(layer['gain']),
                 'color1': [0.0] * 3, 'color2': [1.0] * 3, 'alpha1': 1.0, 'alpha2': 1.0}, **colours)


class ModoProcedurals(unittest.TestCase):
    """Environment Grids and Dots against Modo's own renders (fixtures/environment_procedurals_modo.json, from
    tools/probe_cl_environment_projections.py's proc_* and thin_* cases through tools/check_environment_projections.py
    fixture): each of the Grid's and Dots' types, their widths, soft edges, bias and gain, under every projection."""

    def test_each_procedural_is_what_modo_renders(self):
        cases = json.loads((ROOT / 'tests/fixtures/environment_procedurals_modo.json').read_text())
        self.assertGreaterEqual(len(cases), 30)
        for name, case in cases.items():
            projection = captured(case['locator']['projType'], case['locator']['projAxis'], case['matrix'], procedural=True,
                                  **{k: (float(v) if k not in ('projType', 'tileU', 'tileV') else v) for k, v in case['locator'].items()
                                     if k not in ('projType', 'projAxis')})
            data = pattern(case['kind'], case['layer'])
            errors = []
            for x, y, z, value in case['samples']:
                found = ep.procedural(projection, data, (x, y, z), procedurals.environment_sample)[0][0]
                # Modo's filtered picture against the exact pattern: a little apart in a soft edge.
                self.assertLess(abs(found - value), .11, '%s at %s' % (name, (x, y, z)))
                errors.append(abs(found - value))
            self.assertLess(sum(errors) / len(errors), .015, name)

    def test_the_lines_and_dots_where_modo_puts_them(self):
        def hard(kind, shape, width):
            return {'kind': kind, 'pattern': shape, 'width': width, 'transition': 0.0, 'bias': .5, 'gain': .5,
                    'color1': [0.0] * 3, 'color2': [1.0] * 3, 'alpha1': 1.0, 'alpha2': 1.0}

        def value(data, u, v):
            return procedurals.environment_sample(data, u, v)[0][0]
        # Square: lines half way across each unit (the surfaces' pattern had them on the whole numbers).
        self.assertEqual(value(hard('grid', 'square', .1), .5, .2), 0.0)
        self.assertEqual(value(hard('grid', 'square', .1), .2, 1.5), 0.0)
        self.assertEqual(value(hard('grid', 'square', .1), 0.0, 0.0), 1.0)
        # Line: across u, on each whole v.
        self.assertEqual(value(hard('grid', 'line', .1), .37, 2.0), 0.0)
        self.assertEqual(value(hard('grid', 'line', .1), 0.0, .5), 1.0)
        # Triangle: a line on each half-way v, two at 60 degrees meeting it at the whole u.
        self.assertEqual(value(hard('grid', 'triangle', .04), .3, .5), 0.0)
        self.assertEqual(value(hard('grid', 'triangle', .04), .3 / math.sqrt(3), .8), 0.0)
        self.assertEqual(value(hard('grid', 'triangle', .04), .6, 1.0), 1.0)
        # Hexagon: points up, a unit across, its rows started again at each whole v.
        self.assertEqual(value(hard('grid', 'hexagon', .04), 0.0, .1), 0.0)
        self.assertEqual(value(hard('grid', 'hexagon', .04), .5, .8), 0.0)
        self.assertEqual(value(hard('grid', 'hexagon', .04), .5, .1), 1.0)
        # Dots: on the whole numbers; Hexagon's on the hexagons' centres.
        self.assertEqual(value(hard('dots', 'square', .3), 3.0, -1.0), 0.0)
        self.assertEqual(value(hard('dots', 'square', .3), .5, .5), 1.0)
        self.assertEqual(value(hard('dots', 'hexagon', .3), .5, 0.05), 0.0)
        self.assertEqual(value(hard('dots', 'hexagon', .3), 0.0, math.sqrt(3) / 2), 0.0)
        # The colours meet over transWidth beyond the line, eased.
        soft = dict(hard('grid', 'square', .2), transition=.3)
        self.assertEqual(value(soft, .6, 0.0), 0.0)
        self.assertAlmostEqual(value(soft, .75, 0.0), .5)
        self.assertEqual(value(soft, .9, 0.0), 1.0)
        # Patterns Modo lays otherwise (a dots 'triangle') as the surfaces' pattern.
        other = dict(hard('dots', 'triangle', .3), transition=.1)
        self.assertEqual(procedurals.environment_sample(other, .3, .4), procedurals.sample(other, .3, .4))

    def test_repeat_modes_and_uv_projections(self):
        data = pattern('grid', {'type': 'square', 'lineWidth': .2, 'transWidth': .3, 'bias': .5, 'gain': .5})
        # A Reset locator's Grid carries on past the image.
        reset = captured('planar', matrix=[.6, 0, 0, 0, 0, .6, 0, 0, 0, 0, .6, 0, 0, 0, 0, 1], tileU='reset', tileV='reset')
        self.assertEqual(ep.procedural(reset, data, (.9, .3, .3), procedurals.environment_sample)[1], 1.0)
        # UV Map: the world's x and z, whatever the locator; Implicit UV and Front Projection one colour.
        turned = [0.841, 0.163, -0.516, 0, 0.051, 0.925, 0.376, 0, 0.539, -0.342, 0.77, 0, 0, 0, 0, 1]
        self.assertEqual(ep.procedural_coordinates(captured('uv', matrix=turned), (.3, .4, .5)), [(.3, .5, 1.0)])
        for kind in ('implicitUV', 'front'):
            self.assertEqual(ep.procedural_coordinates(captured(kind), (.3, .4, .5)), [(0.0, 0.0, 1.0)])
            self.assertEqual(ep.coordinates(captured(kind), (.3, .4, .5)), [(0.0, 0.0, 1.0)])
        self.assertEqual(ep.numbers(captured('uv'))[1], 3.0)
        self.assertEqual(ep.numbers(captured('front'))[1], 0.0)

    def test_a_plain_spherical_procedural_is_evaluated_as_modo_does(self):
        layer = {'kind': 'procedural', 'effect': 'envColor', 'opacity': 1.0, 'blend': 'normal', 'invert': False, 'groups': [],
                 'procedural': pattern('grid', {'type': 'square', 'lineWidth': .1, 'transWidth': .1, 'bias': .5, 'gain': .5}),
                 'matrix': IDENTITY, 'scale': [4.0, 3.0], 'rotation': .5}
        made = environment_layers.with_projections({'kind': 'stack', 'layers': [layer]})['layers'][0]
        self.assertEqual(made['projection']['projection'], 'spherical')
        self.assertEqual(made['projection']['wrap'], [4.0, 3.0])
        self.assertEqual(made['projection']['uv_rotation'], .5)
        # An image is left as it is.
        image = dict(layer, kind='image')
        self.assertIs(environment_layers.with_projections({'layers': [image]})['layers'][0], image)


class LightProbe(unittest.TestCase):
    def test_turned_and_sized_unevenly_modo_turns_by_the_columns(self):
        # Modo's renders (fixtures/environment_projections_modo.json lightprobe_rotsize, _rotsize_x, _placed, checked in
        # test_each_projection_looks_up_where_modo_does): the locator's columns made unit and square in turn.
        turned = [0.841, 0.163, -0.516, 0.051, 0.925, 0.376, 0.539, -0.342, 0.77]
        rows = ep.probe_turn(turned, [1.0, 1.0, 1.0])
        for i in range(3):
            for j in range(3):
                self.assertAlmostEqual(rows[i][j], turned[j * 3 + i], 2)   # turned alone: its transpose
        self.assertEqual(ep.probe_turn([1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0], [2.0, .5, 1.5]), [[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]])
        both = ep.probe_turn(turned, [2.0, .5, 1.5])
        for i in range(3):
            self.assertAlmostEqual(sum(v * v for v in both[i]), 1.0)
            for j in range(i):
                self.assertAlmostEqual(sum(a * b for a, b in zip(both[i], both[j])), 0.0)
        # Its first row is the locator's first column, made unit length; not the transpose of its turn.
        column = [turned[0] * 2.0, turned[3] * .5, turned[6] * 1.5]
        length = math.sqrt(sum(v * v for v in column))
        self.assertEqual([round(v, 6) for v in both[0]], [round(v / length, 6) for v in column])
        self.assertGreater(abs(both[1][0] - turned[1]), .1)
        cases = json.loads((ROOT / 'tests/fixtures/environment_projections_modo.json').read_text())
        for name in ('lightprobe_rotsize', 'lightprobe_rotsize_x', 'lightprobe_placed'):
            self.assertIn(name, cases)


class Switch(unittest.TestCase):
    class Locator:
        def __init__(self, **channels):
            self.channels = dict({'projType': 'planar', 'projAxis': 1}, **channels)

    def channel(self, item, key, default=None):
        return item.channels.get(key, default)

    def test_on_lays_the_projection_off_refuses_as_before(self):
        locator = self.Locator()
        matrix = lambda item: IDENTITY
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_ENVIRONMENT_PROJECTIONS': '1'}), \
                mock.patch('moonray_modo.native._switch', side_effect=lambda key, variable: os.environ.get(variable, '1') == '1'):
            self.assertEqual(environments.projection(locator, self.channel, matrix)['projection'], 'planar')
            self.assertIsNone(environments.projection(self.Locator(projType='spherical'), self.channel, matrix))
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_ENVIRONMENT_PROJECTIONS': '0'}), \
                mock.patch('moonray_modo.native._switch', side_effect=lambda key, variable: os.environ.get(variable, '1') == '1'):
            self.assertIsNone(environments.projection(locator, self.channel, matrix))
        # The refusal itself is kept for the switch off.
        text = (KIT / 'python/moonray_modo/environments.py').read_text(encoding='utf-8')
        self.assertIn('environment images require Spherical projection (latitude/longitude)', text)
        self.assertIn('Environment procedurals require a spherical Texture Locator', text)

    def test_preference_wiring(self):
        # On by default (preferences.KEYS; its module needs Modo's Qt).
        self.assertIn("'environment_projections': (True, bool),", (KIT / 'python/moonray_modo/preferences.py').read_text(encoding='utf-8'))
        self.assertIn("lx.bless(switch('environment_projections'),'moonray.pref.environmentProjections')",
                      (KIT / 'lxserv/moonray_preferences.py').read_text(encoding='utf-8'))
        page = (KIT / 'preferences.cfg').read_text(encoding='utf-8')
        start = page.index('cmd moonray.pref.environmentProjections ?')
        block = page[start:page.index('</list>', start)]
        self.assertIn('Environment images in every projection', block)
        self.assertIn('off, such a layer is left out', block)
        block.encode('ascii')
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_ENVIRONMENT_PROJECTIONS': '0'}), \
                mock.patch('moonray_modo.native._switch', side_effect=lambda key, variable: os.environ.get(variable, '1') == '1'):
            self.assertFalse(native.environment_projections())

    def test_projected_layers_are_baked_as_placed(self):
        layer = {'kind': 'image', 'effect': 'envColor', 'opacity': 1, 'blend': 'normal', 'invert': False, 'groups': [],
                 'image_channel': 'ignore', 'matrix': [0, 0, -1.0, 0, 0, 1.0, 0, 0, 1.0, 0, 0, 0, 0, 0, 0, 1],
                 'projection': captured('planar')}
        self.assertIsNone(environment_layers.held_placement({'kind': 'stack', 'layers': [layer]}))
        self.assertTrue(environments.covers(layer))
        self.assertFalse(environments.covers(dict(layer, projection=captured('planar', tileU='reset'))))
        older = mock.Mock(spec=['MR_environment_blend', 'MR_environment_layers', 'MR_gather', 'MR_iota'])
        with mock.patch('moonray_modo.rows._native', return_value=older):
            self.assertFalse(environment_layers.native_layers([layer]))


def adapter():
    for build in sorted((ROOT / 'build').glob('modo-geometry*/MoonRayGeometry.lx'), key=lambda p: -p.stat().st_mtime):
        try:
            held = ctypes.CDLL(str(build))
        except OSError:
            continue
        if hasattr(held, 'MR_environment_projected'):
            return held
    return None


class NativeBake(unittest.TestCase):
    def composed(self, layers, library, folder):
        pixels = (tuple(v for y in range(128) for x in range(256) for v in ((x + .5) / 256, (y + .5) / 128, .25)), None)
        with mock.patch('moonray_modo.environment_layers.cache_root', return_value=pathlib.Path(folder)), \
                mock.patch('moonray_modo.environment_layers.image_pixels', return_value=pixels), \
                mock.patch('moonray_modo.rows._native', return_value=library), \
                mock.patch('moonray_modo.textures.prepare', side_effect=lambda path, *a, **k: path):
            made = pathlib.Path(environment_layers.texture({'kind': 'stack', 'layers': layers}, 256, 128))
        return array.array('f', made.read_bytes().split(b'\n', 3)[3])

    def test_the_adapter_lays_every_projection_as_python_does(self):
        held = adapter()
        if held is None:
            self.skipTest('geometry adapter with MR_environment_projected not built (tools/build_modo_bridge.py)')
        turned = [0.841, 0.163, -0.516, 0, 0.051, 0.925, 0.376, 0, 0.539, -0.342, 0.77, 0, 0, 0, 0, 1]
        sized = [2.0 * v if i < 4 else .5 * v if i < 8 else 1.5 * v if i < 12 else v for i, v in enumerate(turned)]
        for kind, axis, matrix, extra in (('planar', 1, sized, {'uvRotation': .5}), ('cylindrical', 0, sized, {'wrapU': 2.0, 'wrapV': 3.0}),
                                          ('spherical', 2, turned, {}), ('cubic', 1, sized, {'tileU': 'mirror'}), ('box', 1, sized, {}),
                                          ('lightprobe', 1, turned, {}), ('triplanar', 1, sized, {'triplanarBlending': .3}),
                                          ('uv', 1, IDENTITY, {}), ('planar', 2, IDENTITY, {'tileU': 'reset', 'tileV': 'edge'})):
            layers = [{'kind': 'color', 'effect': 'envColor', 'opacity': 1.0, 'blend': 'normal', 'invert': False, 'groups': [], 'color': [.1, .2, .3]},
                      {'kind': 'image', 'effect': 'envColor', 'opacity': 1.0, 'blend': 'normal', 'invert': False, 'groups': [],
                       'path': 'uv.exr', 'matrix': matrix, 'projection': captured(kind, axis, matrix, **extra)}]
            with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
                laid = []
                real = environment_layers.native_blend
                with mock.patch('moonray_modo.environment_layers.native_layers', return_value=True), \
                        mock.patch('moonray_modo.environment_layers.native_blend', side_effect=lambda *x: laid.append(real(*x)) or laid[-1]):
                    made = self.composed(layers, held, a)
                self.assertTrue(laid and laid[0] is not None, kind + ': not laid by the adapter')
                with mock.patch('moonray_modo.environment_layers.native_layers', return_value=False):
                    python = self.composed(layers, None, b)
            self.assertEqual(len(made), len(python), kind)
            worst = max(abs(x - y) for x, y in zip(made, python))
            self.assertLess(worst, 1e-4, kind)

    def test_the_adapter_lays_modo_procedurals_as_python_does(self):
        held = adapter()
        if held is None or not environment_layers.projections_laid(held):
            self.skipTest('geometry adapter with MR_environment_projections_version 2 not built (tools/build_modo_bridge.py)')
        turned = [0.841, 0.163, -0.516, 0, 0.051, 0.925, 0.376, 0, 0.539, -0.342, 0.77, 0, 0, 0, 0, 1]
        sized = [.5 * v if i < 4 else .25 * v if i < 8 else .4 * v if i < 12 else v for i, v in enumerate(turned)]
        grids = [('grid', shape, .2, .3) for shape in ('line', 'square', 'triangle', 'hexagon')] + \
                [('dots', shape, .6, .3) for shape in ('square', 'hexagon')] + [('grid', 'square', .3, 0.0), ('dots', 'triangle', .6, .2)]
        projections = [('planar', 1, sized, {'uvRotation': .5}), ('cylindrical', 0, sized, {'wrapU': 2.0}), ('spherical', 2, turned, {}),
                       ('cubic', 1, sized, {}), ('box', 1, sized, {}), ('lightprobe', 1, sized, {}), ('uv', 1, turned, {}),
                       ('front', 1, IDENTITY, {}), ('planar', 1, sized, {'tileU': 'reset'}), (None, 1, turned, {})]
        for index, (laid, axis, matrix, extra) in enumerate(projections * 2):
            kind, shape, width, soft = grids[index % len(grids)]
            data = {'kind': kind, 'pattern': shape, 'width': width, 'transition': soft, 'bias': .4, 'gain': .6,
                    'color1': [.9, .2, .1], 'color2': [.1, .3, .8], 'alpha1': 1.0, 'alpha2': .5}
            layer = {'kind': 'procedural', 'effect': 'envColor', 'opacity': 1.0, 'blend': 'normal', 'invert': False, 'groups': [],
                     'procedural': data, 'matrix': matrix, 'scale': [1.0, 1.0], 'rotation': 0.0}
            if laid:
                layer['projection'] = captured(laid, axis, matrix, procedural=True, **extra)
            layers = [{'kind': 'color', 'effect': 'envColor', 'opacity': 1.0, 'blend': 'normal', 'invert': False, 'groups': [],
                       'color': [.1, .2, .3]}, layer]
            with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
                laid_by = []
                real = environment_layers.native_blend
                with mock.patch('moonray_modo.environment_layers.native_blend', side_effect=lambda *x: laid_by.append(real(*x)) or laid_by[-1]):
                    made = self.composed(layers, held, a)
                self.assertTrue(laid_by and laid_by[0] is not None, '%s %s: not laid by the adapter' % (shape, laid))
                with mock.patch('moonray_modo.environment_layers.native_layers', return_value=False):
                    python = self.composed(layers, None, b)
            worst = max(abs(x - y) for x, y in zip(made, python))
            self.assertLess(worst, 1e-4, '%s %s %s' % (kind, shape, laid))


if __name__ == '__main__':
    unittest.main()
