"""A sea packed again at each step of a drag (moonlightipr_scene.pack): its bands' variance worked out once for the same
numbers, its tiles found on disk trusted for a while without looking for them or marking them used again, and both
forgotten as the folder is trimmed or the cache cleared. On a test dragon's sea a step took 500 ms, 65 after. No Modo."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import ocean

SEA = {'size': 50.0, 'wind_speed': 8.0, 'wind_direction': 0.0, 'wave_height': 1.0, 'choppiness': 1.0, 'small_waves': 0.0,
       'wind_alignment': 2.0, 'against_wind': 0.5, 'depth': 200.0, 'seed': 1, 'loop': 0.0, 'foam_threshold': 0.5,
       'resolution': 32, 'k_low': 0.0, 'k_high': 0.0, 'fixed_scale': 1.0, 'speed': 1.0, 'cascades': True,
       'time_scale': 1.0, 'time_offset': 0.0}


class Variance(unittest.TestCase):
    def setUp(self):
        ocean._VARIANCES.clear()

    def test_the_same_numbers_once(self):
        with mock.patch.object(ocean, '_band_variance', wraps=ocean._band_variance) as worked:
            first = ocean.cascade_values(dict(SEA))
            again = ocean.cascade_values(dict(SEA))
        self.assertEqual(first, again)
        self.assertEqual(worked.call_count, len(ocean.CASCADES))

    def test_other_numbers_their_own(self):
        with mock.patch.object(ocean, '_band_variance', wraps=ocean._band_variance) as worked:
            ocean.cascade_values(dict(SEA))
            ocean.cascade_values(dict(SEA, wind_speed=12.0))
        self.assertEqual(worked.call_count, 2 * len(ocean.CASCADES))


class Tiles(unittest.TestCase):
    def setUp(self):
        ocean.forget_seen()
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(ocean.forget_seen)
        stem = Path(self.folder.name) / 'tile'
        self.made = (stem.with_suffix('.displacement.pfm'), stem.with_suffix('.foam.pfm'), stem.with_suffix('.slope.pfm'))
        for path in self.made:
            path.write_bytes(b'x')

    def test_a_tile_seen_is_trusted_for_a_while(self):
        with mock.patch.object(ocean, 'paths', return_value=self.made), mock.patch.object(ocean, 'used', wraps=ocean.used) as marked:
            for _ in range(5):
                self.assertEqual(ocean.make(dict(SEA), 0.0), self.made)
        self.assertEqual(marked.call_count, 1)

    def test_looked_for_again_once_forgotten(self):
        with mock.patch.object(ocean, 'paths', return_value=self.made), mock.patch.object(ocean, 'used', wraps=ocean.used) as marked:
            ocean.make(dict(SEA), 0.0)
            ocean.forget_seen()
            ocean.make(dict(SEA), 0.0)
        self.assertEqual(marked.call_count, 2)

    def test_clearing_the_cache_and_trimming_forget(self):
        source = (Path(ocean.__file__).parent / 'cache_folder.py').read_text(encoding='utf-8')
        self.assertIn('ocean.forget_seen()', source)
        self.assertIn('forget_seen', ocean.trim.__code__.co_names)


if __name__ == '__main__':
    unittest.main()
