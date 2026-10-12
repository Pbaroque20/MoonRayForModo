import sys, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo.incremental import transform_targets

class Targets(unittest.TestCase):
    def fixture(self):
        child=SimpleNamespace(id='child')
        owner=SimpleNamespace(id='mesh',children=Mock(return_value=[child]))
        transform=SimpleNamespace(type='translation',itemGraph=lambda _:SimpleNamespace(forward=lambda:[owner]))
        return SimpleNamespace(items=Mock(return_value=[]),item=lambda _:transform),owner
    def test_includes_descendants_without_unrelated_meshes(self):
        scene,owner=self.fixture()
        self.assertEqual(transform_targets(scene,{'move'}),{'mesh','child'})
        owner.children.assert_called_once_with(recursive=True)
    def test_instances_keep_full_refresh(self):
        scene,_=self.fixture();scene.items.return_value=[object()]
        self.assertIsNone(transform_targets(scene,{'move'}))
    def test_unknown_owner_keeps_full_refresh(self):
        scene,_=self.fixture();scene.item=lambda _:SimpleNamespace(type='unknown')
        self.assertIsNone(transform_targets(scene,{'move'}))
    def test_no_notices_keeps_full_refresh_for_release(self):
        scene,_=self.fixture()
        self.assertIsNone(transform_targets(scene,set()))

    def test_channel_modifiers_keep_full_refresh(self):
        scene,_=self.fixture()
        scene.items.side_effect=lambda kind,**kw:[object()] if kind=='chanModify' else []
        self.assertIsNone(transform_targets(scene,{'move'}))

    def test_refresh_updates_owner_and_child_only(self):
        import types
        from unittest.mock import patch
        from moonray_modo.incremental import refresh_transforms
        scene,owner=self.fixture()
        transform=scene.item('move')
        scene.item=lambda identity:transform if identity=='move' else SimpleNamespace(id=identity)
        matrix=Mock(side_effect=lambda item:[item.id])
        fake=types.ModuleType('moonray_modo.host');fake.world_matrix=matrix
        snapshot={'meshes':[{'identity':key,'matrix':['old']} for key in ('mesh','child','unrelated')]}
        with patch.dict(sys.modules,{'moonray_modo.host':fake}):
            refresh_transforms(scene,snapshot,{'move'})
        self.assertEqual([m['matrix'] for m in snapshot['meshes']],[['mesh'],['child'],['old']])
        self.assertEqual(matrix.call_count,2)
