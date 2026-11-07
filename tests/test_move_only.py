"""A drag that only moves things is followed from the scene sent last, its matrices made new and nothing else read
(incremental.move_only); anything it cannot vouch for is read the usual way (None)."""
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo.incremental import move_only


def where(item):
    return [item.id, 'now']


class MoveOnly(unittest.TestCase):
    def setUp(self):
        fake = types.ModuleType('moonray_modo.host')
        fake.world_matrix = Mock(side_effect=where)
        self.patch = patch.dict(sys.modules, {'moonray_modo.host': fake})
        self.patch.start()
        self.matrix = fake.world_matrix

    def tearDown(self):
        self.patch.stop()

    def scene(self, owner='mesh', children=(), others=None, kind='translation'):
        items = {name: SimpleNamespace(id=name, type='mesh', children=Mock(return_value=[]))
                 for name in ('mesh', 'other', 'cam', 'light', 'root')}
        for name in children:
            items[name] = SimpleNamespace(id=name, type='mesh')
        items[owner].children = Mock(return_value=[items[name] for name in children])
        items['move'] = SimpleNamespace(id='move', type=kind,
                                        itemGraph=lambda _: SimpleNamespace(forward=lambda: [items[owner]]))
        items['lens'] = SimpleNamespace(id='cam', type='camera')
        return SimpleNamespace(items=Mock(side_effect=lambda kind, **kw: (others or {}).get(kind, [])),
                               item=lambda identity: items['lens'] if identity == 'cam' else items[identity])

    def snapshot(self, **extra):
        base = {'camera': {'identity': 'cam', 'matrix': ['cam', 'then'], 'focal_mm': 50},
                'meshes': [{'identity': 'mesh|0|uv', 'matrix': ['mesh', 'then']}, {'identity': 'other|0|uv', 'matrix': ['other', 'then']}],
                'lights': [{'identity': 'light', 'matrix': ['light', 'then']}], 'materials': {'': {}}, 'width': 640}
        base.update(extra)
        return base

    def test_a_mesh_moved_is_given_its_place_and_the_rest_kept(self):
        before = self.snapshot()
        after = move_only(self.scene(), before, ['move'])
        self.assertEqual([m['matrix'] for m in after['meshes']], [['mesh', 'now'], ['other', 'then']])
        self.assertIs(after['lights'], before['lights'])
        self.assertIs(after['camera'], before['camera'])
        self.assertEqual(before['meshes'][0]['matrix'], ['mesh', 'then'])

    def test_the_camera_moved_by_navigating(self):
        after = move_only(self.scene(), self.snapshot(), [], camera_moved=True)
        self.assertEqual(after['camera'], {'identity': 'cam', 'matrix': ['cam', 'now'], 'focal_mm': 50})

    def test_the_camera_moved_by_its_transform(self):
        after = move_only(self.scene(owner='cam'), self.snapshot(), ['move'])
        self.assertEqual(after['camera']['matrix'], ['cam', 'now'])

    def test_an_item_named_elsewhere_is_read_the_usual_way(self):
        # A light hanging from the mesh moved.
        self.assertIsNone(move_only(self.scene(children=('light',)), self.snapshot(), ['move']))
        # A mesh named by a material (a texture locator's place, a mesh light).
        self.assertIsNone(move_only(self.scene(), self.snapshot(materials={'tag': {'locator': 'mesh'}}), ['move']))

    def test_what_is_not_a_move_is_read_the_usual_way(self):
        self.assertIsNone(move_only(self.scene(kind='mesh'), self.snapshot(), ['move']))
        self.assertIsNone(move_only(self.scene(), self.snapshot(), ['cam']))

    def test_with_instances_every_mesh_is_asked_where_it_stands(self):
        # Modo may move more than the item moved carries: as a move read the usual way, every mesh is asked.
        after = move_only(self.scene(others={'meshInst': [object()]}), self.snapshot(), ['move'])
        self.assertEqual([m['matrix'] for m in after['meshes']], [['mesh', 'now'], ['other', 'now']])
        # Still read the usual way where what it carries is named elsewhere.
        self.assertIsNone(move_only(self.scene(children=('light',), others={'meshInst': [object()]}), self.snapshot(), ['move']))

    def test_volumes_and_dicing_cameras_are_read_the_usual_way(self):
        volume = self.snapshot(meshes=[{'identity': 'mesh|0|uv', 'matrix': [], 'volumetric': True}])
        self.assertIsNone(move_only(self.scene(), volume, ['move']))
        self.assertIsNone(move_only(self.scene(), self.snapshot(dicing_camera={'identity': 'cam'}), [], camera_moved=True))


if __name__ == '__main__':
    unittest.main()
