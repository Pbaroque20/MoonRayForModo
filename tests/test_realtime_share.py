"""Realtime Sample %: 30 until it is changed, and what it is changed to stays. No Modo."""
import sys
import types
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
sys.modules.setdefault('modo', types.ModuleType('modo'))
sys.modules.setdefault('lx', types.ModuleType('lx'))
from moonray_modo import scene_settings, xpu2_sampling

ENTRY = next(entry for entry in scene_settings.FIELDS if entry['key'] == 'xpu2_realtime')


def share(stored):
    return scene_settings.get(scene_settings.complete(stored), ENTRY)


class RealtimeShare(unittest.TestCase):
    def test_a_scene_that_has_not_chosen_starts_at_30(self):
        self.assertEqual(share({}), 30)

    def test_another_generation_setting_leaves_it_free(self):
        self.assertEqual(share({'xpu2_generations': {'samples': 64}}), 30)

    def test_a_change_is_what_the_scene_keeps(self):
        for value in (55, 100, 30):
            stored = {}
            scene_settings.put(stored, ENTRY, value)
            self.assertEqual(stored['xpu2_generations']['realtime'], value)
            self.assertEqual(share(stored), value)

    def test_realtime_takes_its_share_and_a_render_takes_them_all(self):
        generations = scene_settings.complete({})['xpu2_generations']
        self.assertEqual(xpu2_sampling.budget(dict(generations, samples=100), 4, realtime=True), 30)
        self.assertEqual(xpu2_sampling.budget(dict(generations, samples=100), 4, realtime=False), 100)


if __name__ == '__main__':
    unittest.main()
