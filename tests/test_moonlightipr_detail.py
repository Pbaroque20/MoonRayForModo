"""MoonLightIPR's cut of subdivided and displaced meshes by their size on screen (moonlightipr_detail): the pixels a
unit covers, a mesh's level near and far, the hysteresis, the budget and whether a coarse cut can be refined."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import moonlightipr_detail as detail  # noqa: E402

CAMERA = {'projection': 'persp', 'focal_mm': 50.0, 'film_mm': 36.0, 'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}


def grid(name, n=8, size=1.0, at=0.0, level=3, subdivision=True):
    """A flat n x n grid of quads, size across, at distance at in front of the camera (along -Z)."""
    step = size / n
    vertices = [[i * step - size / 2, j * step - size / 2, 0.0] for j in range(n + 1) for i in range(n + 1)]
    faces = [[j * (n + 1) + i, j * (n + 1) + i + 1, (j + 1) * (n + 1) + i + 1, (j + 1) * (n + 1) + i] for j in range(n) for i in range(n)]
    matrix = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, -at, 1]
    return {'name': name, 'identity': name, 'vertices': vertices, 'faces': faces, 'matrix': matrix, 'subdivision': subdivision,
            'subdivision_level': level}


class Detail(unittest.TestCase):
    def setUp(self):
        detail._HELD.clear()
        detail._EXTENT.clear()

    def test_pixels_per_unit(self):
        self.assertAlmostEqual(detail.pixels_per_unit(CAMERA, 640, [0, 0, -10], 0.0), 640 * 50 / (36 * 10), places=6)
        self.assertAlmostEqual(detail.pixels_per_unit(dict(CAMERA, projection='ortho', ortho_width=4.0), 640, [0, 0, -10], 0.0), 160.0)

    def test_near_meshes_are_cut_finer_than_far_ones_and_never_past_modo(self):
        near, far = grid('near', at=2.0), grid('far', at=400.0)
        cuts, _ = detail.plan([near, far], CAMERA, 640)
        self.assertEqual(cuts[id(near)]['subdivision'], 3)       # Modo's level is the most
        self.assertEqual(cuts[id(far)]['subdivision'], 0)
        self.assertGreater(cuts[id(near)]['splits'], cuts[id(far)]['splits'])

    def test_a_small_move_keeps_the_level(self):
        mesh = grid('held', at=40.0, level=6)
        first = detail.plan([mesh], CAMERA, 640)[0][id(mesh)]['subdivision']
        nudged = dict(mesh, matrix=mesh['matrix'][:14] + [-41.0, 1])
        self.assertEqual(detail.plan([nudged], CAMERA, 640)[0][id(nudged)]['subdivision'], first)
        # Four times as far: a level and more coarser.
        far = dict(mesh, matrix=mesh['matrix'][:14] + [-160.0, 1])
        self.assertLess(detail.plan([far], CAMERA, 640)[0][id(far)]['subdivision'], first)

    def test_a_small_move_keeps_a_dense_mesh_as_it_was_simplified(self):
        # The error is held with the step: the same simplified mesh, not one made (and built) anew for each move.
        mesh = grid('dense', n=160, at=200.0, subdivision=False)
        first = detail.plan([mesh], CAMERA, 640)[0][id(mesh)]['simplify']
        self.assertIsNotNone(first)
        nudged = dict(mesh, matrix=mesh['matrix'][:14] + [-205.0, 1])
        self.assertEqual(detail.plan([nudged], CAMERA, 640)[0][id(nudged)]['simplify'], first)

    def test_coarse_and_fine_simplify_alike(self):
        # Simplified coarser while editing, every dense mesh was simplified again at rest (a car's 26 s): one cut for both.
        mesh = grid('dense', n=160, at=200.0, subdivision=False)
        coarse = detail.plan([mesh], CAMERA, 640, 'coarse')[0][id(mesh)]['simplify']
        fine = detail.plan([mesh], CAMERA, 640, 'fine')[0][id(mesh)]['simplify']
        self.assertIsNotNone(fine)
        self.assertEqual(coarse, fine)
        self.assertFalse(detail.plan([mesh], CAMERA, 640, 'coarse')[1])

    def test_the_budget_cuts_every_mesh_coarser(self):
        meshes = [grid('m%d' % i, n=40, at=1.0, level=6) for i in range(8)]
        displaced = lambda mesh: True
        loose, _ = detail.plan(meshes, CAMERA, 640, 'fine', displaced)
        held = detail.BUDGET['fine']
        try:
            detail.BUDGET['fine'] = 50000
            detail._HELD.clear()
            tight, _ = detail.plan(meshes, CAMERA, 640, 'fine', displaced)
        finally:
            detail.BUDGET['fine'] = held
        self.assertLess(sum(c['subdivision'] + c['splits'] for c in tight.values()), sum(c['subdivision'] + c['splits'] for c in loose.values()))

    def test_coarse_is_refinable_only_where_it_cut_coarser(self):
        mesh = grid('mid', at=20.0, level=6)
        cuts, refinable = detail.plan([mesh], CAMERA, 640, 'coarse')
        self.assertTrue(refinable)
        tiny = grid('tiny', at=5000.0, level=6)
        self.assertFalse(detail.plan([tiny], CAMERA, 640, 'coarse')[1])

    def test_instances_are_judged_by_the_nearest(self):
        mesh = grid('instanced', at=0.0, level=6)
        mesh['instances'] = [mesh['matrix'][:14] + [-500.0, 1], mesh['matrix'][:14] + [-5.0, 1]]
        alone = dict(grid('one', at=0.0, level=6), matrix=mesh['matrix'][:14] + [-5.0, 1])
        self.assertEqual(detail.plan([mesh], CAMERA, 640)[0][id(mesh)], detail.plan([alone], CAMERA, 640)[0][id(alone)])


if __name__ == '__main__':
    unittest.main()
