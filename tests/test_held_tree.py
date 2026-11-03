"""The Shader Tree is walked once for a reading of the scene (layers.held_tree), not again for each material's stack, and
found anew at the next reading."""
import sys
import types
import unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import layers


class Item:
    def __init__(self, identity, children=()):
        self.id = identity
        self._children = list(children)
        self.walked = 0

    def children(self):
        self.walked += 1
        return self._children


class Held(unittest.TestCase):
    def test_walked_once_while_held_and_again_after(self):
        render = Item('render', [Item('a'), Item('b', [Item('c')])])
        with layers.held_tree():
            first = layers.ordered(render)
            again = layers.ordered(render)
            with layers.held_tree():
                inner = layers.ordered(render)
        self.assertIs(first, again)
        self.assertIs(first, inner)
        self.assertEqual([i.id for i in first], ['b', 'c', 'a'])
        self.assertEqual(render.walked, 1)
        self.assertIsNone(layers._HELD)
        layers.ordered(render)
        self.assertEqual(render.walked, 2)

    def test_mask_targets_found_once_while_held(self):
        layer = types.SimpleNamespace(id='m', parent=None)
        found = mock.Mock(return_value='target')
        with mock.patch.object(layers, '_layer_mask_target', found):
            with layers.held_tree():
                self.assertEqual(layers.layer_mask_target(layer, None), 'target')
                self.assertEqual(layers.layer_mask_target(layer, None), 'target')
            layers.layer_mask_target(layer, None)
        self.assertEqual(found.call_count, 2)


if __name__ == '__main__':
    unittest.main()
