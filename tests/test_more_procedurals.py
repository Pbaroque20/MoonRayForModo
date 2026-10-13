import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import procedurals


def made(kind, **held):
    values = dict(procedurals.EXTRA[kind])
    values.update(held)
    def channel(layer, name, default=None):
        return values.get(name, default)
    layer = type('Layer', (), {'type': kind})()
    return procedurals.capture(layer, channel, lambda layer, name, default=(0, 0, 0): list(default), False)


class LaterPatterns(unittest.TestCase):
    def test_each_repeats_without_a_seam(self):
        for kind in procedurals.EXTRA:
            data = made(kind)
            for u, v in ((.13, .27), (.5, .91), (.02, .5)):
                a, b = procedurals.sample(data, u, v), procedurals.sample(data, u + 1, v + 2)
                self.assertAlmostEqual(a[0][0], b[0][0], places=6, msg=kind)
            if kind == 'weave':
                # Its yarns end at every square's edge, the tile's among them.
                continue
            edge = [abs(procedurals.sample(data, .0005, v / 16.0)[0][0] - procedurals.sample(data, .9995, v / 16.0)[0][0]) for v in range(16)]
            self.assertLess(sum(edge) / len(edge), .08, kind)

    def test_each_has_light_and_dark_in_it(self):
        for kind in procedurals.EXTRA:
            data = made(kind)
            values = [procedurals.sample(data, (x + .5) / 24, (y + .5) / 24)[0][0] for x in range(24) for y in range(24)]
            self.assertLess(min(values), .35, kind)
            self.assertGreater(max(values), .65, kind)
            self.assertTrue(all(0 <= value <= 1 for value in values), kind)

    def test_value_1_and_value_2_are_the_ends(self):
        data = made('ripples')
        data.update(color1=[.8] * 3, color2=[.2] * 3)
        values = [procedurals.sample(data, (x + .5) / 24, (y + .5) / 24)[0][0] for x in range(24) for y in range(24)]
        self.assertGreaterEqual(min(values), .2 - 1e-9)
        self.assertLessEqual(max(values), .8 + 1e-9)

    def test_a_wider_cell_fills_more(self):
        def filled(width):
            data = made('cellular', cellWidth=width, transWidth=0.0)
            return sum(procedurals.sample(data, (x + .5) / 32, (y + .5) / 32)[0][0] for x in range(32) for y in range(32))
        # Value 1, the cell's, is 0 here and Value 2, between the cells, is 1: more cell is less light.
        self.assertLess(filled(.9), filled(.3))


if __name__ == '__main__':
    unittest.main()
