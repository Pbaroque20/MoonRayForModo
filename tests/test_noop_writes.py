"""Edits that change nothing are not edits: a value entered as it is held (give or take a float's last digits) is the
same value, and a material's settings written as they already are write nothing and tell nothing, so realtime and
MoonLightIPR do not start again (properties.same_value, properties.write). No Modo launch."""
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))


def load_properties():
    """moonray_modo.properties with stand-ins for Modo's modules, taken away again after."""
    held = {name: sys.modules.get(name) for name in ('modo', 'moonray_modo.properties')}
    sys.modules['modo'] = types.ModuleType('modo')
    sys.modules.pop('moonray_modo.properties', None)
    try:
        from moonray_modo import properties
        return properties
    finally:
        for name, module in held.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


properties = load_properties()


class Item:
    def __init__(self, tag=None):
        self.tag, self.writes = tag, 0

    def readTag(self, key):
        if self.tag is None:
            raise LookupError(key)
        return self.tag

    def setTag(self, key, value):
        self.tag, self.writes = value, self.writes + 1


class SameValue(unittest.TestCase):
    def test_numbers(self):
        self.assertTrue(properties.same_value(0, 0.0))
        self.assertTrue(properties.same_value(0.3, 0.30000000000000004))
        self.assertTrue(properties.same_value(1000.0, 1000.0004))
        self.assertFalse(properties.same_value(0.3, 0.301))
        self.assertFalse(properties.same_value(0.0, 1e-5))

    def test_colours_and_others(self):
        self.assertTrue(properties.same_value([0.3, 0, 1], (0.30000000000000004, 0.0, 1.0)))
        self.assertFalse(properties.same_value([0.3, 0, 1], [0.3, 0, 0.9]))
        self.assertFalse(properties.same_value([0.3, 0], [0.3, 0, 0]))
        self.assertTrue(properties.same_value('a', 'a'))
        self.assertFalse(properties.same_value(True, 1.0000001))
        self.assertFalse(properties.same_value(None, 0))


class Write(unittest.TestCase):
    def setUp(self):
        self.notified = []
        notifications = types.ModuleType('moonray_modo.property_notifications')
        notifications.notify = lambda: self.notified.append(True)
        self.patches = [mock.patch.dict(sys.modules, {'moonray_modo.property_notifications': notifications}),
                        mock.patch.object(properties, 'mark_shader', lambda item, values: None)]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()

    def test_the_same_settings_write_nothing(self):
        values = {'native_shader': 'DwaBaseMaterial', 'native_parameters': {'roughness': 0.5}}
        item = Item(json.dumps(values, sort_keys=True, separators=(',', ':')))
        properties.write(item, dict(values))
        self.assertEqual((item.writes, self.notified), (0, []))

    def test_other_settings_are_written_and_told(self):
        item = Item(json.dumps({'native_parameters': {'roughness': 0.5}}, sort_keys=True, separators=(',', ':')))
        properties.write(item, {'native_parameters': {'roughness': 0.7}})
        self.assertEqual((item.writes, self.notified), (1, [True]))

    def test_a_first_write_is_written(self):
        item = Item()
        properties.write(item, {'native_parameters': {}})
        self.assertEqual(item.writes, 1)


if __name__ == '__main__':
    unittest.main()
