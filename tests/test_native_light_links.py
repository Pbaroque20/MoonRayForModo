"""Modo's own light links, as written for MoonRay: each mesh's light set is filed under the material its parts render
with, which is the base one ('') where its polygon tag has no material of its own."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import native_light_links


def written(materials, mode):
    scene = {'materials': materials,
             'native_light_links': {'lights': {'sun': {'mode': mode, 'members': ['left']}}, 'materials': {}}}
    meshes = [{'identity': 'left', 'material': 'Default'}, {'identity': 'right', 'material': 'Default'}]
    lines = []
    native_light_links.emit(scene, meshes, {'sun': ['DistantLight("/modo/light/sun")']}, [], lines)
    return '\n'.join(lines)


class Filed(unittest.TestCase):
    def test_a_tag_without_a_material_of_its_own_is_filed_under_the_base_one(self):
        text = written({'': {}}, 'exclude')
        self.assertIn('nativeLightSets["left"][""] = LightSet("/modo/nativeLinks/0")', text)
        self.assertIn('nativeLightSets["right"][""] = LightSet("/modo/nativeLinks/1")', text)
        self.assertNotIn('["Default"]', text)

    def test_a_tag_with_its_own_material_keeps_it(self):
        self.assertIn('nativeLightSets["left"]["Default"]', written({'': {}, 'Default': {}}, 'include'))

    def test_excluded_and_included_sets(self):
        # Excluded, the left mesh's set is empty and the right one's holds the light; included, the other way round.
        text = written({'': {}}, 'exclude')
        self.assertIn('LightSet("/modo/nativeLinks/0")({})', text)
        self.assertIn('LightSet("/modo/nativeLinks/1")({DistantLight("/modo/light/sun")})', text)
        text = written({'': {}}, 'include')
        self.assertIn('nativeLightSets["left"][""] = LightSet("/modo/nativeLinks/0")', text)
        self.assertIn('LightSet("/modo/nativeLinks/0")({DistantLight("/modo/light/sun")})', text)
        self.assertIn('LightSet("/modo/nativeLinks/1")({})', text)
        self.assertIn('nativeLightSets["right"][""] = LightSet("/modo/nativeLinks/1")', text)


if __name__ == '__main__':
    unittest.main()
