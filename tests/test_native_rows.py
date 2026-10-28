"""The geometry adapter's gathering and finite check (MR_gather, MR_finite), done away from Python's lock: the same as
the plugin's own Python gives, and refusing a place beyond the rows."""
import math
import os
import pathlib
import sys
import unittest
from array import array

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
ADAPTER = ROOT / 'build/modo-bridge-detail/MoonRayGeometry.lx'


@unittest.skipUnless(ADAPTER.is_file(), 'Requires the built geometry adapter')
class NativeRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ['MOONRAY_MODO_GEOMETRY'] = str(ADAPTER)
        from moonray_modo import rows, simplify
        cls.rows = rows
        if rows._native() is None:
            raise unittest.SkipTest('The adapter has no MR_gather')
        cls.simplify = simplify

    def test_gather_is_the_same_as_picking_in_python(self):
        points = array('f', [float(i) for i in range(30)])
        places = array('I', [3, 0, 9, 3])
        gathered = self.rows.gather(points, 12, places)
        self.assertEqual(list(gathered), [v for p in places for v in points[3 * p:3 * p + 3]])
        self.assertIsNone(self.rows.gather(points, 12, array('I', [10])))

    def test_finite(self):
        self.assertTrue(self.rows.finite(array('f', [0.0, 1.5, -2.0])))
        self.assertFalse(self.rows.finite(array('f', [0.0, math.inf])))
        self.assertFalse(self.rows.finite(array('f', [math.nan])))
        self.assertTrue(self.rows.finite(array('f')))

    def test_simplify_gather_uses_it_and_agrees(self):
        values = array('f', [float(i) for i in range(20)])
        places = [4, 1, 1, 9]
        self.assertEqual(list(self.simplify._gather(values, 2, places)), [v for p in places for v in values[2 * p:2 * p + 2]])


if __name__ == '__main__':
    unittest.main()
