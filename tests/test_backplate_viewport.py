"""A Backplate's photo in Modo's viewport: a Modo Backdrop (reference image) for each Backplate whose "backplate in
the viewport" is on and that has a photo: Camera projection behind everything, or at Backdrop Distance a card in front
of the render camera filling its view; made, changed and taken away to follow them. Checked in
Modo by tools/probe_gui_backplate_viewport.py."""
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import backplate_viewport  # noqa: E402

KIT = ROOT / 'kit/MoonRayForModo'


class Item:
    def __init__(self, ident, **channels):
        self.id, self.values = ident, channels

    def channel(self, name):
        if name not in self.values:
            raise LookupError(name)
        return type('C', (), {'get': lambda _, v=self.values[name]: v})()


def plate(**values):
    return Item('bp1', **{'mr_' + k: v for k, v in values.items()})


class Want(unittest.TestCase):
    def test_none_without_a_photo_or_switched_off(self):
        self.assertEqual(backplate_viewport.want(plate(plate=''), None), '')
        self.assertEqual(backplate_viewport.want(plate(plate='C:/a.jpg', viewport_plate=False), None), '')

    def test_behind_everything_at_distance_0(self):
        setup = json.loads(backplate_viewport.want(plate(plate='C:/Photos/A.jpg', backdrop_distance=0.0), None))
        self.assertEqual(setup, {'photo': 'c:/photos/a.jpg', 'path': 'C:/Photos/A.jpg'})

    def test_a_card_filling_the_camera_view_at_its_distance(self):
        # 36 mm film, 50 mm lens, 10 m ahead: 7.2 m across, over a 3,600-pixel photo: 2 mm a pixel.
        camera = Item('cam', focalLen=0.05, apertureX=0.036, projType='persp')
        setup = json.loads(backplate_viewport.want(plate(plate='C:/a.jpg', backdrop_distance=10.0), camera, width=lambda path: 3600))
        self.assertEqual((setup['card'], setup['camera'], setup['distance']), (True, 'cam', 10.0))
        self.assertAlmostEqual(setup['pixel'], 0.002)


class Plan(unittest.TestCase):
    def test_made_where_wanted(self):
        self.assertEqual(backplate_viewport.plan({'bp1': 'A', 'bp2': ''}, []), ([], [('bp1', 'A')], []))

    def test_left_alone_in_order(self):
        # Nothing to do, so a scene in order gets no undo step.
        self.assertEqual(backplate_viewport.plan({'bp1': 'A'}, [('bd1', 'bp1', 'A')]), ([], [], []))

    def test_set_up_again_when_it_changes(self):
        self.assertEqual(backplate_viewport.plan({'bp1': 'B'}, [('bd1', 'bp1', 'A')]), ([], [], [('bd1', 'B')]))

    def test_taken_away(self):
        # Switched off (or no photo), its Backplate deleted, or a second one for the same Backplate.
        plan = backplate_viewport.plan({'bp1': '', 'bp2': 'A'},
                                       [('bd1', 'bp1', 'A'), ('bd2', 'gone', 'A'), ('bd3', 'bp2', 'A'), ('bd4', 'bp2', 'A')])
        self.assertEqual(plan, (['bd1', 'bd2', 'bd4'], [], []))


class Wiring(unittest.TestCase):
    def test_the_option(self):
        catalog = json.loads((KIT / 'python/moonray_modo/entity_catalog.json').read_text(encoding='utf-8'))

        def find(node):
            if isinstance(node, dict):
                if 'BackplateEnvironment' in node and 'attributes' in node['BackplateEnvironment']:
                    return node['BackplateEnvironment']
                for value in node.values():
                    found = find(value)
                    if found:
                        return found
        spec = find(catalog)['attributes']['viewport_plate']
        self.assertEqual((spec['type'], spec['default'], spec['group'], spec['label']),
                         ('Bool', True, 'Backplate', 'backplate in the viewport'))
        self.assertIn('mr_viewport_plate', (KIT / 'entities.cfg').read_text(encoding='utf-8'))

    def test_kept_up_by_a_command_on_changes(self):
        source = (KIT / 'lxserv/moonray_entities.py').read_text(encoding='utf-8')
        self.assertIn("lx.bless(BackplateViewport,'moonray.backplate.viewport')", source)
        self.assertIn('backplate_channels={entities.CHANNEL_PREFIX+key for key in _viewport.PLATE_KEYS}', source)
        self.assertEqual(backplate_viewport.PLATE_KEYS, ('plate', 'viewport_plate', 'backdrop_distance'))
        for hook in ('def sil_ItemRemove', 'def sil_ChannelValue', 'QtCore.QTimer.singleShot(0,backplate_viewport_later)'):
            self.assertIn(hook, source)
        module = (KIT / 'python/moonray_modo/backplate_viewport.py').read_text(encoding='utf-8')
        self.assertIn("backdrop$projection %s' % ('front' if card else 'camera')", module)


if __name__ == '__main__':
    unittest.main()
