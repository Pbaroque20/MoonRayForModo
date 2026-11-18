"""A Shift-drag on a colour's swatch in the MoonShine graph editor (node_widgets.VectorField.shift_drag) makes it brighter or
darker, all its parts together, as Modo's does (parameter_state.brightened). A request: from the colour the drag began
with, so that dragged up to white and back down in the same drag it is that colour again, not a grey."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo.parameter_state import BRIGHTER_PER_PIXEL, brightened  # noqa: E402

ORANGE = [1.0, .5, .2]


class Brightened(unittest.TestCase):
    def test_all_parts_move_together(self):
        for got, expected in zip(brightened(ORANGE, -20), [.9, .4, .1]):
            self.assertAlmostEqual(got, expected)

    def test_kept_between_black_and_white(self):
        self.assertEqual(brightened(ORANGE, 1 / BRIGHTER_PER_PIXEL), [1.0, 1.0, 1.0])
        self.assertEqual(brightened(ORANGE, -1 / BRIGHTER_PER_PIXEL), [0.0, 0.0, 0.0])

    def test_up_to_white_and_back_is_the_same_colour(self):
        # Each step from the colour the drag began with: white on the way, then back where it started.
        self.assertEqual(brightened(ORANGE, 400), [1.0, 1.0, 1.0])
        for got, expected in zip(brightened(ORANGE, 0), ORANGE):
            self.assertAlmostEqual(got, expected)
        for got, expected in zip(brightened(ORANGE, -40), [.8, .3, 0.0]):
            self.assertAlmostEqual(got, expected)


if __name__ == '__main__':
    unittest.main()
