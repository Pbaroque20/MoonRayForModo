"""A Shader item's visibility switches (evaluated.shader_switches): a Shader put above a surface's base Shader with
Visible to Camera off hides the surface from the camera and keeps it in reflections, as Modo renders it. Modo's own
surface flags, which the geometry adapter hands over, do not carry them (a tester's report)."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import evaluated  # noqa: E402


class Channel:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class Item:
    def __init__(self, identity, kind='defaultShader', children=(), **channels):
        self.id, self.type, self._children, self.channels = identity, kind, list(children), channels

    def children(self):
        return self._children

    def channel(self, name):
        if name not in self.channels:
            raise LookupError(name)
        return Channel(self.channels[name])


class Scene:
    def __init__(self, *layers):
        # Modo lists a parent's children bottom of the Shader Tree first: the last is the highest.
        self.renderItem = Item('render', 'polyRender', layers)
        self.items = {layer.id: layer for layer in layers}

    def item(self, identity):
        return self.items[identity]


ON = dict(visCam=1, visInd=1, visRefl=1, visRefr=1, shadCast=1)


class ShaderSwitches(unittest.TestCase):
    def test_an_override_shader_above_hides_from_the_camera(self):
        base = Item('base', visEnable=1, lgtEnable=1, **ON)
        override = Item('over', visEnable=1, lgtEnable=0, **dict(ON, visCam=0))
        switches = evaluated.shader_switches(Scene(base, override), ('base', 'over'), {})
        self.assertEqual(switches, (False, True, True, True, True))

    def test_a_shader_not_controlling_visibility_leaves_it_to_the_one_under(self):
        base = Item('base', visEnable=1, lgtEnable=1, **dict(ON, visRefl=0))
        override = Item('over', visEnable=0, lgtEnable=1, **dict(ON, shadCast=0))
        switches = evaluated.shader_switches(Scene(base, override), ('base', 'over'), {})
        self.assertEqual(switches, (True, True, False, True, False))

    def test_without_control_switches_the_highest_shader_as_before(self):
        base = Item('base', **ON)
        override = Item('over', **dict(ON, shadCast=0, visRefr=0))
        self.assertEqual(evaluated.shader_switches(Scene(base, override), ('base', 'over'), {}),
                         (True, True, True, False, False))
        self.assertFalse(evaluated.casts_shadow(Scene(base, override), ('base', 'over'), {}))

    def test_only_the_surfaces_own_layers_count(self):
        base = Item('base', visEnable=1, **ON)
        other = Item('other', visEnable=1, **dict(ON, visCam=0))
        self.assertTrue(evaluated.shader_switches(Scene(base, other), ('base',), {})[0])


if __name__ == '__main__':
    unittest.main()
