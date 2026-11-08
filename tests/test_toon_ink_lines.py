"""Issue 134: Toon lines in a colour (a MoonRay Source Override), the Compositor's Ink Lines node, and a Toon filter's
lines alone saved as lines of one colour with their cover as alpha. No Modo or renderer launch."""
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import compositor, entities, image_formats, toon_lines

TOON = {'identity': 'toon', 'name': 'Toon', 'class': 'ToonDisplayFilter',
        'parameters': {'output_mode': 1, 'ink_color': [0.1, 0.0, 0.5]}}


def graph(mix=0.6, lines=True):
    nodes = {'a': ('input', {'buffer': 'beauty'}, {}), 'l': ('input', {'buffer': 'toon'}, {}),
             'i': ('ink_lines', {'color': [0.1, 0.0, 0.5], 'mix': mix}, dict({'image': 'a'}, **({'lines': 'l'} if lines else {}))),
             'out': ('output', {}, {'image': 'i'})}
    return {'nodes': {k: {'type': t, 'parameters': p, 'inputs': i, 'position': [0, 0]} for k, (t, p, i) in nodes.items()}, 'root': 'out'}


class InkColourOverride(unittest.TestCase):
    def test_written_with_the_switch_on_left_out_with_it_off(self):
        with mock.patch.object(entities, 'toon_ink_color', lambda: True):
            self.assertEqual(entities.completed_filters([TOON], [])[0]['parameters']['ink_color'], [0.1, 0.0, 0.5])
        with mock.patch.object(entities, 'toon_ink_color', lambda: False):
            self.assertNotIn('ink_color', entities.completed_filters([TOON], [])[0]['parameters'])

    def test_in_the_catalog_and_the_filter_source(self):
        self.assertIn('ink_color', entities.catalog()['ToonDisplayFilter']['attributes'])
        source = ROOT / 'upstream/openmoonray/moonray/moonshine/dso/displayfilter/ToonDisplayFilter/ToonDisplayFilter.ispc'
        self.assertIn('inkColor.r * (1.0f - ink)', source.read_text(encoding='utf-8'))


class InkLinesNode(unittest.TestCase):
    def test_colour_laid_on_as_much_as_the_lines_cover(self):
        beneath, cover = (0.8, 0.6, 0.4), {0: 0.0, 1: 0.5, 2: 1.0, 3: 1.3}
        for x, c in cover.items():
            got = compositor.sample(graph(), lambda k: beneath if k == 'beauty' else (c, c, c), x, 0, 4, 1)['out']
            t = min(c, 1.0) * 0.6
            for g, b, ink in zip(got, beneath, (0.1, 0.0, 0.5)):
                self.assertAlmostEqual(g, b + (ink - b) * t)

    def test_no_lines_is_the_picture(self):
        got = compositor.sample(graph(lines=False), lambda k: (0.8, 0.6, 0.4), 0, 0, 1, 1)['out']
        self.assertEqual(got, (0.8, 0.6, 0.4))

    def test_program_merges_the_ink_through_the_clamped_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            compositor.jobs(graph(), {'beauty': 'B.exr', 'toon': 'T.exr'}, {'beauty': 'beauty', 'toon': 'beauty'}, folder, composite='modo_composite.exe')
            text = (pathlib.Path(folder) / 'composite.txt').read_text(encoding='utf-8').splitlines()
        kinds = [int(line.split()[1]) for line in text if line.startswith('step')]
        self.assertEqual(kinds, [compositor.STEP_KINDS[k] for k in ('constant', 'clamp', 'merge')])

    def test_listed_in_the_editor_merge_group(self):
        source = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/compositor_editor.py').read_text(encoding='utf-8')
        self.assertIn("'ink_lines'", source)


class LinesSaved(unittest.TestCase):
    def test_lines_alone_found_with_their_colour(self):
        snapshot = {'entities': [TOON]}
        key = entities.filter_key(TOON)
        with mock.patch.object(entities, 'toon_ink_color', lambda: True), mock.patch.object(entities, 'toon_lines_apart', lambda: True):
            self.assertEqual(entities.ink_lines(snapshot, key), (0.1, 0.0, 0.5))
            self.assertIsNone(entities.ink_lines(snapshot, 'beauty'))
            shading = {'entities': [dict(TOON, parameters={'output_mode': 0})]}
            self.assertIsNone(entities.ink_lines(shading, key))
        with mock.patch.object(entities, 'toon_ink_color', lambda: False), mock.patch.object(entities, 'toon_lines_apart', lambda: True):
            self.assertEqual(entities.ink_lines(snapshot, key), (0.0, 0.0, 0.0))

    def test_exr_premultiplied_png_straight(self):
        exr = image_formats.lines_with_alpha('exr32', 'T.exr', (0.1, 0.0, 0.5), 'out.exr')
        self.assertIn('0.1,0,0.5,1', exr)
        self.assertIn('R,G,B,A', exr)
        png = image_formats.lines_with_alpha('png8', 'T.exr', (0.1, 0.0, 0.5), 'out.png')
        self.assertIn('--addc', png)
        self.assertEqual(png[png.index('--chappend') - 1], 'A')
        self.assertIn('oiio:UnassociatedAlpha', png)


class SmoothLinesOverride(unittest.TestCase):
    def test_written_with_the_switch_on_left_out_with_it_off(self):
        with mock.patch.object(entities, 'toon_smooth_lines', lambda: True):
            self.assertIs(entities.completed_filters([TOON], [])[0]['parameters'].get('smooth_lines'), True)
        with mock.patch.object(entities, 'toon_smooth_lines', lambda: False):
            self.assertNotIn('smooth_lines', entities.completed_filters([TOON], [])[0]['parameters'])

    def test_in_the_catalog_and_the_filter_source(self):
        self.assertIn('smooth_lines', entities.catalog()['ToonDisplayFilter']['attributes'])
        source = (ROOT / 'upstream/openmoonray/moonray/moonshine/dso/displayfilter/ToonDisplayFilter/ToonDisplayFilter.cc').read_text(encoding='utf-8')
        self.assertIn('get(attrSmoothLines) ? 6', source)


class FinalRenderLines(unittest.TestCase):
    def test_the_part_holding_the_lines_gets_their_alpha(self):
        parts = [['R', 'G', 'B', 'A'], ['Toon.R', 'Toon.G', 'Toon.B'], ['depth.Z']]
        args = toon_lines.arguments(parts, {'Toon': (0.1, 0.0, 0.5)}, 'in.exr', 'out.exr')
        self.assertEqual(args.count('--subimage'), 3)
        self.assertEqual(args.count('--siappend'), 2)
        self.assertIn('Toon.R,Toon.G,Toon.B,Toon.A=Toon.R', args)
        self.assertIn('0.1,0,0.5,1', args)
        self.assertEqual(args[-2:], ['-o', 'out.exr'])

    def test_lines_in_the_first_part_keep_the_other_channels(self):
        args = toon_lines.arguments([['R', 'G', 'B', 'A', 'Toon.R', 'Toon.G', 'Toon.B']], {'Toon': (1.0, 0.0, 0.0)}, 'in.exr', 'out.exr')
        self.assertIn('R,G,B,A,Toon.R,Toon.G,Toon.B,Toon.A=Toon.R', args)
        self.assertIn('1,1,1,1,1,0,0,1', args)
        self.assertNotIn('--siappend', args)

    def test_nothing_to_do(self):
        self.assertIsNone(toon_lines.arguments([['R', 'G', 'B', 'A']], {'Toon': (0, 0, 0)}, 'in.exr', 'out.exr'))
        self.assertIsNone(toon_lines.arguments([['Toon.R', 'Toon.G', 'Toon.B', 'Toon.A']], {'Toon': (0, 0, 0)}, 'in.exr', 'out.exr'))

    def test_only_toon_filters_giving_lines_alone(self):
        shading = dict(TOON, name='Shade', identity='s', parameters={'output_mode': 0})
        with mock.patch.object(entities, 'toon_lines_apart', lambda: True), mock.patch.object(entities, 'toon_ink_color', lambda: True),              mock.patch.object(entities, 'display_filters', lambda s: s['entities']):
            self.assertEqual(toon_lines.wanted({'entities': [TOON, shading]}), {'Toon': (0.1, 0.0, 0.5)})


if __name__ == '__main__':
    unittest.main()
