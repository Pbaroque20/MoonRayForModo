"""Hues and angles in the graph editor have a slider, over the range each goes round. No Modo."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python/moonray_modo'
sys.path.insert(0, str(ROOT.parent))
from moonray_modo import parameter_state


def classes(catalog):
    held = json.loads((ROOT / catalog).read_text(encoding='utf-8'))
    return held.get('classes', held)


def spec(catalog, shader, key):
    return classes(catalog)[shader]['attributes'][key]


class Wiring(unittest.TestCase):
    def test_the_property_list_gives_a_hue_or_an_angle_the_slider(self):
        source = (ROOT / 'node_editor.py').read_text(encoding='utf-8')
        self.assertIn('from .parameter_state import slider_range', source)
        self.assertIn('RadialField(identity,key,layer,spec,value,span,', source)
        self.assertIn('NumericField,RadialField,', source)


class Ranges(unittest.TestCase):
    def test_a_declared_range_comes_first(self):
        self.assertEqual(parameter_state.slider_range('hue_shift', spec('map_catalog.json', 'ColorCorrectMap', 'hue_shift')), (0.0, 1.0))
        self.assertEqual(parameter_state.slider_range('hue_shift', spec('material_catalog.json', 'DwaColorCorrectMaterial', 'hue_shift')), (0.0, 1.0))

    def test_a_hue_in_degrees_goes_all_the_way_round(self):
        self.assertEqual(parameter_state.slider_range('hue_shift', spec('map_catalog.json', 'ColorCorrectHsvMap', 'hue_shift')), (0.0, 360.0))
        self.assertEqual(parameter_state.slider_range('hue', spec('map_catalog.json', 'ColorCorrectLegacyMap', 'hue')), (0.0, 360.0))

    def test_angles(self):
        self.assertEqual(parameter_state.slider_range('rotation_angle', spec('map_catalog.json', 'ImageMap', 'rotation_angle')), (-180.0, 180.0))
        self.assertEqual(parameter_state.slider_range('crease_threshold', spec('map_catalog.json', 'ToonMap', 'crease_threshold')), (0.0, 180.0))
        self.assertEqual(parameter_state.slider_range('primary_specular_offset', spec('material_catalog.json', 'HairMaterial_v3', 'primary_specular_offset')), (-10.0, 10.0))

    def test_every_radial_name_is_a_number_on_some_node(self):
        kinds = {}
        for catalog in ('map_catalog.json', 'material_catalog.json'):
            for entry in classes(catalog).values():
                if isinstance(entry, dict):
                    for key, held in (entry.get('attributes') or {}).items():
                        kinds.setdefault(key, set()).add(held.get('type'))
        for key in parameter_state.RADIAL:
            self.assertIn('Float', kinds.get(key, ()), key)

    def test_anything_else_has_none(self):
        self.assertIsNone(parameter_state.slider_range('roughness', {'type': 'Float'}))
        self.assertIsNone(parameter_state.slider_range('rotation', {'type': 'Vec3f'}))


if __name__ == '__main__':
    unittest.main()
