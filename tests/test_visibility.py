"""What Modo hides is left out of a render: an item's eye and its Render setting, and the kinds of ray a surface is
hidden from, as MoonLightIPR is told them."""
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

for name in ('modo', 'lx', 'lxifc', 'lxu', 'lxu.utils'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import host, moonlightipr_scene


class Item:
    def __init__(self, visible='default', render='default', parent=None):
        self.values = {'visible': visible, 'render': render}
        self.parent = parent


def shown(item):
    with mock.patch.object(host, 'channel', lambda item, name, default=None: item.values.get(name, default)):
        return host.render_visible(item)


class RenderVisible(unittest.TestCase):
    def test_default_follows_the_eye(self):
        self.assertTrue(shown(Item()))
        self.assertFalse(shown(Item(visible='off')))
        self.assertFalse(shown(Item(visible='allOff')))

    def test_render_setting_settles_it(self):
        self.assertTrue(shown(Item(visible='off', render='on')))
        self.assertFalse(shown(Item(render='off')))

    def test_a_parent_hides_its_children_only_when_told_to(self):
        self.assertTrue(shown(Item(parent=Item(visible='off'))))
        self.assertFalse(shown(Item(parent=Item(visible='allOff'))))
        self.assertFalse(shown(Item(parent=Item(render='off'))))
        self.assertTrue(shown(Item(visible='default', parent=Item(visible='allOff', render='on'))))
        self.assertFalse(shown(Item(visible='off', parent=Item(render='on'))))


class SeenBy(unittest.TestCase):
    def test_every_ray_finds_a_surface_that_says_nothing(self):
        self.assertEqual(moonlightipr_scene.seen_by({}), 255)

    def test_bits_follow_modos_order(self):
        # camera, indirect, reflection, refraction, subsurface, shadow
        self.assertEqual(moonlightipr_scene.seen_by({'visibility': [True] * 6}), 31)
        self.assertEqual(moonlightipr_scene.seen_by({'visibility': [False, True, True, True, True, True]}), 30)
        self.assertEqual(moonlightipr_scene.seen_by({'visibility': [False, False, False, False, False, True]}), 16)
        self.assertEqual(moonlightipr_scene.seen_by({'visibility': [True, False, False, False, True, False]}), 1)


if __name__ == '__main__':
    unittest.main()
