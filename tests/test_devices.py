"""Device Management: the devices XPU2 lists, their switches, and what XPU2 is started with. No Modo."""
import importlib.util
import sys
import types
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo'
sys.path.insert(0, str(ROOT / 'python'))
from moonray_modo import devices  # noqa: E402

LISTED = ('group\t0\t32\tAMD Ryzen 9 7950X 16-Core Processor\n'
          'group\t1\t32\tAMD Ryzen 9 7950X 16-Core Processor\n'
          'card\t0\taaaa\t25757220864\tNVIDIA GeForce RTX 4090\n'
          'card\t1\tbbbb\t8589934592\tNVIDIA GeForce RTX 3070\n')


class Store(dict):
    def get_(self, key, default=''): return self.get(key, default)


class DevicesTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        found = devices.parse(LISTED)
        self.patches = [patch.object(devices, '_get', self.store.get_), patch.object(devices, '_set', self.store.__setitem__),
                        patch.object(devices, 'listed', lambda again=False: found)]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in self.patches: p.stop()

    def test_listing_is_read(self):
        groups, cards = devices.parse(LISTED + 'junk\ncard\tx\n')
        self.assertEqual([g['number'] for g in groups], [0, 1])
        self.assertEqual([(c['index'], c['uuid']) for c in cards], [(0, 'aaaa'), (1, 'bbbb')])
        self.assertEqual(devices.card_label(cards[0]), 'NVIDIA GeForce RTX 4090, 24 GB')
        self.assertEqual(devices.group_label(groups[1], groups), 'AMD Ryzen 9 7950X 16-Core Processor, group 1, 32 threads')

    def test_everything_on_at_first(self):
        self.assertEqual(devices.mode(), 'both')
        self.assertEqual(devices.environment(), {})
        self.assertEqual(devices.summary(), '2 of 2 graphics cards on, 2 of 2 processor groups on')

    def test_former_choice_is_taken_over(self):
        self.store['xpu2/devices'] = 'gpu'
        self.assertEqual(devices.mode(), 'gpu')
        self.store['xpu2/devices'] = 'cpu'
        self.assertEqual(devices.mode(), 'cpu')
        # The first switch keeps the rest as they were: the cards stay off.
        self.assertTrue(devices.switch('group', 1, False))
        self.assertEqual(devices.mode(), 'cpu')
        self.assertEqual(devices.environment(), {'XPU2_CARD_LIST': '', 'XPU2_GROUP_LIST': '0'})

    def test_a_card_off_is_left_out(self):
        self.assertTrue(devices.switch('card', 0, False))
        self.assertEqual(devices.environment(), {'XPU2_CARD_LIST': '1'})
        self.assertEqual(devices.mode(), 'both')
        self.assertTrue(devices.switch('card', 1, False))
        self.assertEqual(devices.mode(), 'cpu')
        self.assertTrue(devices.switch('card', 0, True))
        self.assertEqual(devices.environment(), {'XPU2_CARD_LIST': '0'})

    def test_last_device_stays_on(self):
        for kind, place in (('card', 0), ('card', 1), ('group', 0)):
            self.assertTrue(devices.switch(kind, place, False))
        self.assertFalse(devices.switch('group', 1, False))
        self.assertEqual(devices.mode(), 'cpu')
        self.assertEqual(devices.environment(), {'XPU2_CARD_LIST': '', 'XPU2_GROUP_LIST': '1'})

    def test_a_card_keeps_its_switch_by_uuid(self):
        self.assertTrue(devices.switch('card', 1, False))
        # The cards numbered otherwise (the 3070 first): the 3070 is still the one off.
        swapped = devices.parse('group\t0\t32\tCPU\ncard\t0\tbbbb\t8589934592\tNVIDIA GeForce RTX 3070\n'
                                'card\t1\taaaa\t25757220864\tNVIDIA GeForce RTX 4090\n')
        with patch.object(devices, 'listed', lambda again=False: swapped):
            self.assertEqual(devices.environment(), {'XPU2_CARD_LIST': '1'})
        # Taken out for a while, it stays off when it is back.
        alone = devices.parse('group\t0\t32\tCPU\ncard\t0\taaaa\t25757220864\tNVIDIA GeForce RTX 4090\n')
        with patch.object(devices, 'listed', lambda again=False: alone):
            self.assertTrue(devices.switch('card', 0, True))
        self.assertEqual(devices.environment(), {'XPU2_CARD_LIST': '0'})

    def test_restart_follows_the_devices(self):
        before = devices.state()
        devices.switch('card', 1, False)
        self.assertNotEqual(devices.state(), before)


class PageTests(unittest.TestCase):
    def test_page_has_a_slot_for_each_device_command(self):
        text = (ROOT / 'preferences.cfg').read_text(encoding='utf-8')
        ElementTree.fromstring(text)
        self.assertTrue(text.isascii())
        for kind, slots in (('card', devices.CARD_SLOTS), ('group', devices.GROUP_SLOTS)):
            for k in range(slots):
                for name in ('Shown', 'Name', 'On'):
                    self.assertIn('moonray.pref.%s%s%d' % (kind, name, k), text)
        # Under XPU2's page, whose devices it chooses: no page of its own.
        self.assertIn('val="sub MoonRayDevices:sheet"', text.split('key="MoonRayXPU2Page:sheet"')[1].split('</hash>')[0])
        self.assertNotIn('prefs/moonray/devices:filterPreset', text)
        self.assertIn('cmd moonray.xpu2.compileShaders', text.split('key="MoonRayDevices:sheet"')[1])
        self.assertNotIn('moonray.pref.xpu2Devices', text)

    def test_commands_are_blessed(self):
        blessed = []
        lx = types.ModuleType('lx')
        lx.bless = lambda server, name: blessed.append(name)
        lxu = types.ModuleType('lxu')
        command = types.ModuleType('lxu.command')
        command.BasicCommand = object
        lxu.command = command
        lxifc = types.ModuleType('lxifc')
        lxifc.Notifier = object
        notifications = types.ModuleType('moonray_modo.property_notifications')
        notifications.Followed = type('Followed', (), {})
        with patch.dict(sys.modules, {'lx': lx, 'lxu': lxu, 'lxu.command': command, 'lxifc': lxifc,
                                      'moonray_modo.property_notifications': notifications}):
            spec = importlib.util.spec_from_file_location('moonray_devices_under_test', ROOT / 'lxserv/moonray_devices.py')
            spec.loader.exec_module(importlib.util.module_from_spec(spec))
        self.assertIn('moonray.pref.cardOn7', blessed)
        self.assertIn('moonray.pref.groupShown3', blessed)
        self.assertIn('moonray.pref.devicesRefresh', blessed)


if __name__ == '__main__':
    unittest.main()
