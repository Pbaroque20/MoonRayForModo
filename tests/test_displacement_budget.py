"""Displacement at Modo's defaults (Displacement Rate 1 pixel, Minimum Edge Length 100 um) on a 10 x 10 m ground seen
from eye height: Modo's cut (read through its render cache) came to 11.5 M triangles, 22 GB in Modo and a 2.9 GB scene
at 1920 x 1080 (tools/probe_cl_displaced_plane.py). It is estimated before it is read and, past a budget, MoonRay
displaces the surfaces itself within one; MoonRay's own cut keeps to Modo's Minimum Edge Length and a triangle cap."""
import math
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

for name in ('modo', 'lx', 'lxifc', 'lxu', 'lxu.utils'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import displacement_budget, host, moonlightipr_scene, rdla


def look(eye, pitch_degrees):
    """A camera at eye looking along -z, pitched down (a row-vector matrix, as host.world_matrix gives)."""
    p = math.radians(pitch_degrees)
    return [1, 0, 0, 0, 0, math.cos(p), -math.sin(p), 0, 0, math.sin(p), math.cos(p), 0, eye[0], eye[1], eye[2], 1]


CAMERA = {'matrix': look((0.0, 1.7, 4.5), 12.0), 'focal_mm': 50, 'film_mm': 36}
GROUND = [[-5, 0, -5], [5, 0, -5], [5, 0, 5], [-5, 0, 5]]


def reading(layers=('displacer',)):
    """An undisplaced reading (evaluated.capture) of the ground: two triangles, as Modo's render cache gives them."""
    return {'prototypes': {'7': {'segments': [{'vertices': GROUND, 'faces': [[0, 1, 2], [0, 2, 3]]}]}},
            'surfaces': [{'source_id': 7, 'matrix': rdla.IDENTITY, 'layers': list(layers)}]}


def displaced_scene(**mesh):
    layer = {'identity': 'layer', 'kind': 'constant', 'effect': 'displace', 'value': [.5, .5, .5], 'opacity': 1,
             'blend': 'normal', 'groups': [], 'absolute_groups': []}
    held = dict({'name': 'ground', 'vertices': GROUND, 'faces': [[0, 1, 2], [0, 2, 3]], 'material': 'ground'}, **mesh)
    return {'camera': dict(CAMERA), 'meshes': [held], 'displacement_min_edge': 0.0001,
            'materials': {'ground': {'color': [.5, .5, .5], 'layers': [layer], 'displacement_distance': 0.1}}}


def resolution(text):
    return int(text.split('["mesh_resolution"] = ')[1].split(',')[0])


class ModoCut(unittest.TestCase):
    def test_estimate_follows_what_modo_made(self):
        # Modo made 11,499,204 triangles at 1 pixel and 1,266,506 at 3 (probe_cl_displaced_plane, 1920 x 1080).
        at_one = displacement_budget.modo_dicing(reading(), {'displacer'}, CAMERA, 1920, 1080, 1.0, 4.0, 0.0001)
        at_three = displacement_budget.modo_dicing(reading(), {'displacer'}, CAMERA, 1920, 1080, 3.0, 4.0, 0.0001)
        self.assertLess(abs(at_one / 11499204 - 1), 0.25)
        self.assertLess(abs(at_three / 1266506 - 1), 0.25)
        self.assertGreater(at_one, displacement_budget.MODO_DISPLACED_TRIANGLES)
        self.assertLess(at_three, displacement_budget.MODO_DISPLACED_TRIANGLES)

    def test_only_displaced_surfaces_count(self):
        self.assertEqual(displacement_budget.modo_dicing(reading(('other',)), {'displacer'}, CAMERA, 1920, 1080), 0.0)

    def test_minimum_edge_length_bounds_the_cut(self):
        # A Minimum Edge Length of 10 cm: at most 2 x 100 m2 / 0.01 m2 triangles, whatever the rate.
        made = displacement_budget.modo_dicing(reading(), {'displacer'}, CAMERA, 1920, 1080, 1.0, 4.0, 0.1)
        self.assertLessEqual(made, 2 * 100 / 0.01 * 1.01)

    def test_rate_that_keeps_modo_cut(self):
        self.assertEqual(displacement_budget.rate_for(12.8e6, 1.0), 1.8)
        self.assertLessEqual(12.8e6 / 1.8 ** 2, displacement_budget.MODO_DISPLACED_TRIANGLES)


class RefusedInHost(unittest.TestCase):
    def refused(self, rate, layers=frozenset({'displacer'})):
        displacement_budget._VERDICTS.clear()
        result = {'camera': dict(CAMERA), 'width': 1920, 'height': 1080, 'displacement_rate': rate,
                  'displacement_ratio': 4.0, 'displacement_min_edge': 0.0001}
        lx = types.SimpleNamespace(service=types.SimpleNamespace(Selection=lambda: types.SimpleNamespace(GetTime=lambda: 0.0)))
        captured = []

        def capture(time, displaced=True, **kwargs):
            captured.append((displaced, host.modo_displaces()))
            return reading()
        from moonray_modo import evaluated
        with mock.patch.object(host, 'lx', lx, create=True), mock.patch.object(host, 'displacing_layers', lambda scene: set(layers)), \
                mock.patch.object(evaluated, 'capture', capture):
            made = host.modo_cut_refused(types.SimpleNamespace(filename='ground.lxo', name='ground'), result)
        return made, captured

    def test_default_rate_is_refused_from_an_undisplaced_reading(self):
        made, captured = self.refused(1.0)
        self.assertGreater(made, displacement_budget.MODO_DISPLACED_TRIANGLES)
        self.assertEqual(captured, [(False, False)])

    def test_three_pixels_keeps_modo_cut(self):
        self.assertIsNone(self.refused(3.0)[0])

    def test_nothing_displaced_reads_nothing(self):
        made, captured = self.refused(1.0, layers=frozenset())
        self.assertIsNone(made)
        self.assertEqual(captured, [])

    def test_estimate_made_once(self):
        displacement_budget._VERDICTS.clear()
        calls = []
        for _ in range(2):
            displacement_budget.verdict(('key',), lambda: calls.append(1) or 5.0)
        self.assertEqual(len(calls), 1)

    def test_refused_cut_says_so(self):
        result = host.refused_cut({'displacement_rate': 1.0, 'warnings': ['a'], 'meshes': [{'evaluated_geometry': True}]}, 12.8e6)
        self.assertIn('a', result['warnings'])
        notice = [w for w in result['warnings'] if 'Displacement Rate' in w]
        self.assertEqual(len(notice), 1)
        self.assertIn('1.8 pixels', notice[0])


class MoonRayCut(unittest.TestCase):
    def test_cut_by_the_screen_as_finely_as_the_budget_allows(self):
        # Read as modeled at Modo's rate, the ground of two triangles may be cut 1414 times along an edge (4 M triangles
        # at the most, far fewer where it is small on screen); at the level's 8 alone it came out flat.
        text = rdla.scene_text(displaced_scene())
        self.assertEqual(resolution(text), int(math.sqrt(displacement_budget.FALLBACK_TRIANGLES / 2)))
        self.assertIn('["adaptive_error"] = 1', text)

    def test_budget_shared(self):
        scene = displaced_scene()
        scene['meshes'].append(dict(scene['meshes'][0], name='second'))
        self.assertEqual(resolution(rdla.scene_text(scene)), int(math.sqrt(displacement_budget.FALLBACK_TRIANGLES / 4)))

    def test_dense_mesh_keeps_its_level(self):
        # A head of 60,000 triangles: the budget allows no more than its level's 8, as before.
        rows = 100
        vertices = [[i * 0.003, j * 0.003, 0] for j in range(rows + 1) for i in range(301)]
        faces = [[j * 301 + i, j * 301 + i + 1, (j + 1) * 301 + i + 1, (j + 1) * 301 + i] for j in range(rows) for i in range(300)]
        self.assertEqual(resolution(rdla.scene_text(displaced_scene(vertices=vertices, faces=faces))), 8)

    def test_uniform_and_instances_keep_the_level(self):
        scene = displaced_scene()
        scene['render_settings'] = {'displacement_tessellation': 0}
        self.assertEqual(resolution(rdla.scene_text(scene)), 8)
        self.assertEqual(resolution(rdla.scene_text(displaced_scene(instances=[rdla.IDENTITY]))), 8)

    def test_own_resolution_kept(self):
        self.assertEqual(resolution(rdla.scene_text(displaced_scene(mesh_resolution=16))), 16)

    def test_minimum_edge_length(self):
        # Edges of about a centimetre (1.14 cm on average) split no shorter than a Minimum Edge Length of 1 cm: in two;
        # no shorter than Modo's 100 um: in 114.
        scene = displaced_scene(vertices=[[x * 0.001 for x in point] for point in GROUND])
        scene['displacement_min_edge'] = 0.01
        self.assertEqual(resolution(rdla.scene_text(scene)), 2)
        scene['displacement_min_edge'] = 0.0001
        self.assertEqual(resolution(rdla.scene_text(scene)),
                         math.ceil(displacement_budget.mean_edge(scene['meshes'][0]) / 0.0001))

    def test_triangle_cap(self):
        class Faces:
            """A million quads as the adapter hands them over (rows.Faces): their counts and corners."""
            counts = True
            data = range(4000000)

            def __len__(self):
                return 1000000
        mesh = {'faces': Faces()}
        self.assertEqual(displacement_budget.triangles(mesh['faces']), 2000000)
        self.assertEqual(displacement_budget.resolution(8, mesh), int(math.sqrt(displacement_budget.DISPLACED_TRIANGLES / 2000000)))
        self.assertEqual(displacement_budget.resolution(2, mesh), 2)


class MoonLightIPRSplit(unittest.TestCase):
    """MoonLightIPR's split of a displaced mesh cut by the screen: a head close up (near and far alike) split evenly,
    its subdivision smooth first; a ground from eye height split by distance as before."""
    def head(self, rings=16, segments=32):
        vertices = [[math.sin(math.pi * r / rings) * math.cos(2 * math.pi * s / segments), math.cos(math.pi * r / rings),
                     math.sin(math.pi * r / rings) * math.sin(2 * math.pi * s / segments)] for r in range(1, rings) for s in range(segments)]
        faces = [[r * segments + s, r * segments + (s + 1) % segments, (r + 1) * segments + (s + 1) % segments, (r + 1) * segments + s]
                 for r in range(rings - 2) for s in range(segments)]
        return {'vertices': vertices, 'faces': faces, 'matrix': rdla.IDENTITY, 'subdivision': True, 'subdivision_level': 2,
                'mesh_resolution': 64}

    def test_spread(self):
        camera = {'matrix': look((0.0, 0.0, 3.0), 0.0), 'focal_mm': 70, 'film_mm': 36}
        self.assertLess(moonlightipr_scene.distance_spread(self.head(), camera), moonlightipr_scene.DISTANCE_SPREAD)
        ground = {'vertices': GROUND, 'faces': [[0, 1, 2, 3]], 'matrix': rdla.IDENTITY}
        self.assertGreater(moonlightipr_scene.distance_spread(ground, CAMERA), moonlightipr_scene.DISTANCE_SPREAD)
        self.assertIsNone(moonlightipr_scene.distance_spread(dict(ground, instances=[rdla.IDENTITY]), CAMERA))

    def test_head_subdivided_smooth_first(self):
        # Its cage of 448 quads subdivided to 5 (32 a side, within the even budget) where it was 2, before the session's
        # flat splits; split by distance, within DISPLACED_TRIANGLES alone.
        camera = {'matrix': look((0.0, 0.0, 3.0), 0.0), 'focal_mm': 70, 'film_mm': 36}
        head = self.head()
        corners = sum(map(len, head['faces']))
        made = moonlightipr_scene.smoother_cage(head, camera, moonlightipr_scene.EVEN_TRIANGLES)
        self.assertEqual(made['subdivision_level'], 5)
        self.assertLessEqual(2 * corners * 4 ** 4, moonlightipr_scene.EVEN_TRIANGLES)
        far = moonlightipr_scene.smoother_cage(head, {'matrix': look((0.0, 0.0, 1.2), 0.0), 'focal_mm': 70, 'film_mm': 36},
                                               moonlightipr_scene.EVEN_TRIANGLES)
        self.assertLessEqual(2 * corners * 4 ** (far['subdivision_level'] - 1), moonlightipr_scene.DISPLACED_TRIANGLES)
        # No finer than its resolution asks.
        self.assertEqual(moonlightipr_scene.smoother_cage(dict(head, mesh_resolution=4), camera, moonlightipr_scene.EVEN_TRIANGLES), dict(head, mesh_resolution=4))


if __name__ == '__main__':
    unittest.main()
