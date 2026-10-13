import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import extra_geometry


class FurBase(unittest.TestCase):
    def test_a_mesh_all_in_fur_marked_remove_base_surface_is_left_out(self):
        meshes = [{'identity': 'mesh1', 'name': 'Fur', 'material': 'PeachFur'}, {'identity': 'mesh2', 'name': 'Berry', 'material': 'Raspberry'}]
        extras = [{'kind': 'curves', 'source_item': 'mesh1', 'fur_only': 'PeachFur'}]
        warnings = []
        self.assertEqual([m['name'] for m in extra_geometry.without_fur_bases(meshes, extras, warnings)], ['Berry'])
        self.assertEqual(warnings, [])

    def test_fur_that_keeps_its_base_changes_nothing(self):
        meshes = [{'identity': 'mesh1', 'name': 'Fur', 'material': 'PeachFur'}]
        self.assertEqual(extra_geometry.without_fur_bases(meshes, [{'kind': 'curves', 'source_item': 'mesh1'}], []), meshes)

    def test_a_mesh_only_partly_in_fur_is_kept_and_said(self):
        meshes = [{'identity': 'mesh1', 'name': 'Head', 'face_materials': ['Skin', 'Hair']}]
        warnings = []
        kept = extra_geometry.without_fur_bases(meshes, [{'kind': 'curves', 'source_item': 'mesh1', 'fur_only': 'Hair'}], warnings)
        self.assertEqual(kept, meshes)
        self.assertEqual(len(warnings), 1)

    def test_instances_of_the_mesh_go_with_it(self):
        meshes = [{'identity': 'mesh1|inst7', 'name': 'Fur', 'material': 'PeachFur'}]
        self.assertEqual(extra_geometry.without_fur_bases(meshes, [{'source_item': 'mesh1', 'fur_only': 'PeachFur'}], []), [])


if __name__ == '__main__':
    unittest.main()
