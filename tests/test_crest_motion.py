"""The crest's motion in the preview: it comes in part by part and settles, breathes while a render is on its way, and
holds still otherwise."""
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
try:
    from moonray_modo import crest
except ImportError:  # no Qt outside Modo
    qt = types.ModuleType('PySide2')
    qt.QtCore, qt.QtGui = types.ModuleType('QtCore'), types.ModuleType('QtGui')
    with mock.patch.dict(sys.modules, {'PySide2': qt, 'PySide2.QtCore': qt.QtCore, 'PySide2.QtGui': qt.QtGui}):
        from moonray_modo import crest


class Entrance(unittest.TestCase):
    def test_nothing_shows_at_first_and_all_is_in_place_once_it_has_come_in(self):
        start, end = crest.entrance(0.0), crest.entrance(crest.ENTRANCE)
        for kind, number in [('arc', 0), ('arc', 1)] + [('letter', n) for n in range(7)]:
            self.assertEqual(start(kind, number)[0], 0.0)
            self.assertEqual(end(kind, number), (1.0, 0.0, 0.0))
        self.assertTrue(crest.entered(crest.ENTRANCE))
        self.assertFalse(crest.entered(crest.ENTRANCE / 2))

    def test_the_arcs_come_from_above_and_below_and_the_letters_one_after_another(self):
        early = crest.entrance(crest.ENTRANCE * 0.15)
        self.assertLess(early('arc', 0)[2], 0.0)
        self.assertGreater(early('arc', 1)[2], 0.0)
        middle = crest.entrance(crest.ENTRANCE * 0.43)
        shown = [middle('letter', n)[0] for n in range(7)]
        self.assertEqual(shown, sorted(shown, reverse=True))
        self.assertGreater(shown[0], shown[-1])


class Breathing(unittest.TestCase):
    def test_a_wave_runs_along_the_letters_and_never_hides_them(self):
        pose = crest.breathing(0.3)
        shown = [pose('letter', n)[0] for n in range(7)]
        self.assertGreater(max(shown) - min(shown), 0.2)
        self.assertGreaterEqual(min(shown), 0.3 - 1e-9)

    def test_without_depth_it_is_still(self):
        pose = crest.breathing(0.7, depth=0.0)
        self.assertEqual({pose('letter', n) for n in range(7)}, {(1.0, 0.0, 0.0)})


if __name__ == '__main__':
    unittest.main()
