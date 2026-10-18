"""Lua counts every local a scene declares, block by block, and MoonRay refuses a scene past 32767: the scene text
declares its blocks' names once, however many meshes, instancers and shapes it has."""
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import rdla

LOCAL = re.compile(r'(?<![\w.])local\s')


def scene(count):
    return {'camera': {'matrix': rdla.IDENTITY, 'focal_mm': 50, 'film_mm': 36},
            'meshes': [{'name': 'mesh%d' % i, 'vertices': [[i, 0, 0], [i + 1, 0, 0], [i, 1, 0]], 'faces': [[0, 1, 2]],
                        'material': '', **({'instances': [rdla.IDENTITY, rdla.IDENTITY]} if i % 2 else {})}
                       for i in range(count)]}


class SceneLocals(unittest.TestCase):
    def test_locals_do_not_grow_with_the_scene(self):
        few, many = (len(LOCAL.findall(rdla.scene_text(scene(count)))) for count in (4, 400))
        self.assertEqual(few, many)
        self.assertLess(many, 100)

    def test_each_block_sets_the_shared_names(self):
        text = rdla.scene_text(scene(2))
        first = text.split('\n', 1)[0]
        self.assertTrue(first.startswith('local '))
        for name in ('geometry', 'instances'):
            self.assertIn(name, first)
        self.assertIn('  geometry = RdlMeshGeometry("/modo/mesh/0")', text)
        self.assertNotIn('local geometry', text)


if __name__ == '__main__':
    unittest.main()
