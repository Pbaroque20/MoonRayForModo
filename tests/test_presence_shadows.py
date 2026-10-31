"""Automatic Presence Shadows: on where a material is cut out by a map, off where none is, whatever Render Settings say;
Render Settings' own while it is not chosen. What each renderer is given. No Modo or renderer launch."""
import sys
import unittest
from unittest import mock
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import presence_shadows


def graph(**inputs):
    return {'node_graph': {'root': 'surface', 'nodes': {'surface': {'type': 'DwaMetalMaterial', 'parameters': {}, 'inputs': inputs}}}}


class CutsOutTests(unittest.TestCase):
    def test_what_counts(self):
        self.assertTrue(presence_shadows.cuts_out({'layers': [{'effect': 'diffCol'}, {'effect': 'stencil'}]}))
        self.assertTrue(presence_shadows.cuts_out({'textures': {'stencil': {}}}))
        self.assertTrue(presence_shadows.cuts_out(graph(presence='img')))
        self.assertTrue(presence_shadows.cuts_out({'node_graph': {'nodes': {}, 'overrides': [{'inputs': {'presence': 'img'}}]}}))

    def test_what_does_not(self):
        for material in ({}, {'layers': []}, {'layers': [{'effect': 'diffCol'}]}, graph(albedo='img'), {'node_graph': None}):
            self.assertFalse(presence_shadows.cuts_out(material))


class RenderValuesTests(unittest.TestCase):
    def values(self, chosen, material, typed):
        scene = {'materials': {'a': material}, 'render_settings': {'enable_presence_shadows': typed}}
        with mock.patch.object(presence_shadows, 'automatic', lambda: chosen):
            return presence_shadows.render_values(scene)['enable_presence_shadows']

    def test_automatic_decides_whatever_is_typed(self):
        stencil = {'layers': [{'effect': 'stencil'}]}
        self.assertTrue(self.values(True, stencil, 0))
        self.assertFalse(self.values(True, {}, 1))

    def test_not_chosen_leaves_render_settings(self):
        self.assertFalse(self.values(False, {'layers': [{'effect': 'stencil'}]}, 0))
        self.assertTrue(self.values(False, {}, 1))

    def test_off_unless_chosen_outside_modo(self):
        self.assertFalse(presence_shadows.automatic())


if __name__ == '__main__':
    unittest.main()
