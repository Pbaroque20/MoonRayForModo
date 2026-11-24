"""Stacked Modo environments hide the ones under them, ray by ray (environments.occlude): a gradient environment over an
HDRI one was added to it, for the camera, lighting, reflections and refractions alike."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import environments  # noqa: E402


def env(name, camera=True, indirect=True, reflection=True, refraction=True, seen=None):
    return {'name': name, 'camera': camera, 'indirect': indirect, 'reflection': reflection, 'refraction': refraction,
            'indirect_seen': indirect if seen is None else seen}


class Occlude(unittest.TestCase):
    def test_the_top_one_hides_the_one_under_it(self):
        kept = environments.occlude([env('gradient'), env('hdri')])
        self.assertEqual([e['name'] for e in kept], ['gradient'])

    def test_each_ray_sees_its_own_topmost(self):
        # The backplate for the camera and reflections, the HDRI for the lighting.
        kept = environments.occlude([env('plate', indirect=False, refraction=False), env('hdri')])
        self.assertEqual([e['name'] for e in kept], ['plate', 'hdri'])
        plate, hdri = kept
        self.assertEqual((plate['camera'], plate['reflection'], plate['indirect']), (True, True, False))
        self.assertEqual((hdri['camera'], hdri['reflection'], hdri['indirect'], hdri['refraction']), (False, False, True, True))

    def test_indirect_off_by_global_illumination_still_hides(self):
        # Visible to Indirect, with Global Illumination off where the preferences follow Modo: no light from either.
        kept = environments.occlude([env('top', indirect=False, seen=True), env('below', camera=False, reflection=False, refraction=False)])
        self.assertEqual([e['name'] for e in kept], ['top'])

    def test_one_environment_is_left_as_it_is(self):
        kept = environments.occlude([env('only', reflection=False)])
        self.assertEqual(len(kept), 1)
        self.assertFalse(kept[0]['reflection'])


if __name__ == '__main__':
    unittest.main()
