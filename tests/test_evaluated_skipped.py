"""A mesh piece Modo has not got ready (LXe_NOTAVAILABLE, a mesh just added and being edited in its tool's
properties) is left out of a reading by the geometry adapter and counted: the scene is read once more, and a piece
still not ready gives a notice rather than stopping the render."""
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import evaluated


class Skipped(unittest.TestCase):
    def test_a_reading_with_pieces_left_out_is_read_again(self):
        readings = iter([{'surfaces': [], 'prototypes': {}, 'skipped': 1}, {'surfaces': [], 'prototypes': {}, 'skipped': 0}])
        with mock.patch.object(evaluated, '_capture', side_effect=lambda *a: next(readings)) as read:
            self.assertEqual(evaluated.capture(0.0)['skipped'], 0)
        self.assertEqual(read.call_count, 2)

    def test_a_whole_reading_is_read_once(self):
        with mock.patch.object(evaluated, '_capture', return_value={'surfaces': [], 'prototypes': {}, 'skipped': 0}) as read:
            evaluated.capture(0.0)
        self.assertEqual(read.call_count, 1)

    def test_pieces_still_left_out_give_a_notice(self):
        warnings = []
        evaluated.meshes({'surfaces': [], 'prototypes': {}, 'skipped': 2}, {}, warnings)
        self.assertTrue(any('not ready' in w for w in warnings))

    def test_the_adapter_counts_rather_than_fails(self):
        source = (ROOT / 'native-modo/render_cache.cpp').read_text(encoding='utf-8')
        self.assertIn('LXe_NOTAVAILABLE', source)
        self.assertIn('"Polygon indices"', source)
        self.assertNotIn('check(segment.GetPolygonVertexInds', source)


if __name__ == '__main__':
    unittest.main()
