"""MoonLightIPR's light sets: which lights reach an instance, by MoonRay's order (an object's Light Links, else its
material's, else Modo's group light links, which keep the environment), packed as a table of bits (the environment,
then each distant light, then each other light) with each instance's set above the eight bits of its visibility."""
import struct
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import moonlightipr_scene

NAMED = {'distant': ['sun'], 'local': ['key', 'fill']}


def instance(seen=31):
    return struct.pack('<2IiI12f', 0, 0, -1, seen, *([0.0] * 12))


def packed(scene, linked):
    instances = [instance() for _ in linked]
    warnings = []
    words, table = moonlightipr_scene.light_sets(scene, NAMED, linked, instances, warnings)
    sets = [struct.unpack_from('<I', record, 12)[0] for record in instances]
    return words, table, sets, warnings


def bits(row):
    return [bit for bit in range(32) if row[0] >> bit & 1]


class LightSets(unittest.TestCase):
    def test_nothing_linked_is_every_light(self):
        words, table, sets, _ = packed({}, [(0, 'ball', [''])])
        self.assertEqual((words, len(table)), (1, 1))
        self.assertEqual(sets, [31])

    def test_an_objects_links_choose_its_lights(self):
        scene = {'production': {'objects': {'ball': {'link_enabled': True, 'lights': ['key']}}}}
        _, table, sets, _ = packed(scene, [(0, 'ball', ['']), (1, 'floor', [''])])
        self.assertEqual(sets[0] & 255, 31)
        self.assertEqual(sets[0] >> 8, 1)
        self.assertEqual(bits(table[1]), [2])     # key: after the environment and the sun
        self.assertEqual(sets[1] >> 8, 0)

    def test_the_environment_is_a_light_to_choose(self):
        scene = {'production': {'objects': {'ball': {'link_enabled': True, 'lights': ['__environment__', 'fill']}}}}
        _, table, sets, _ = packed(scene, [(0, 'ball', [''])])
        self.assertEqual(bits(table[sets[0] >> 8]), [0, 3])

    def test_a_materials_links_when_the_object_has_none(self):
        scene = {'materials': {'red': {'rdl_layer_links': {'link_enabled': True, 'lights': ['sun']}}}}
        _, table, sets, _ = packed(scene, [(0, 'ball', ['red'])])
        self.assertEqual(bits(table[sets[0] >> 8]), [1])

    def test_modo_group_links_keep_the_environment(self):
        scene = {'native_light_links': {'lights': {'key': {'mode': 'exclude', 'members': ['ball']}}, 'materials': {}}}
        _, table, sets, _ = packed(scene, [(0, 'ball', [''])])
        self.assertEqual(bits(table[sets[0] >> 8]), [0, 1, 3])

    def test_the_same_links_share_a_set(self):
        scene = {'production': {'objects': {name: {'link_enabled': True, 'lights': ['key']} for name in ('a', 'b')}}}
        _, table, sets, _ = packed(scene, [(0, 'a', ['']), (1, 'b', [''])])
        self.assertEqual(len(table), 2)
        self.assertEqual(sets[0], sets[1])

    def test_materials_lit_differently_are_named(self):
        scene = {'materials': {'red': {'rdl_layer_links': {'link_enabled': True, 'lights': ['sun']}}}}
        _, _, _, warnings = packed(scene, [(0, 'ball', ['red', 'blue'])])
        self.assertTrue(any('linked to different lights' in w for w in warnings))


if __name__ == '__main__':
    unittest.main()
