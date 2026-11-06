"""Checker through its texture locator as Modo lays it (procedurals.checker_rows). The cases are points from Modo's
own renders of a plane at z = 0 (tools/probe_cl_checker_variants.py): the locator scaled 0.3 and turned 30 degrees
about X and Y, on each projection axis, and its colour there (True for colour 2)."""
import math
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'kit' / 'MoonRayForModo' / 'python'))
from moonray_modo import procedurals  # noqa: E402


def turned(ax, ay, s, position=(0.0, 0.0, 0.0)):
    """The kit's rows (world to locator) for a locator at position, scaled s, turned ax about X then ay about Y."""
    cx, sx, cy, sy = math.cos(ax), math.sin(ax), math.cos(ay), math.sin(ay)
    rx = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    ry = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    rotation = [[sum(rx[i][k] * ry[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    back = [[rotation[j][i] / s for j in range(3)] for i in range(3)]
    return [back[i] + [-sum(back[i][j] * position[j] for j in range(3))] for i in range(3)]


def colour(rows, point, cube=False):
    """ModoProceduralMap's checker: colour 2 where the parity is even (modo_patterns.h mp_checker)."""
    local = [sum(r[k] * point[k] for k in range(3)) + r[3] for r in rows]
    parity = (math.floor(local[0]) + math.floor(local[1]) + (math.floor(local[2]) if cube else 0)) & 1
    return parity == 0


class CheckerRows(unittest.TestCase):
    def test_square_on_each_axis_follows_modo(self):
        rows = turned(math.radians(30), math.radians(30), 0.3)
        # Modo's rule, as fitted to every pixel of its renders: the point's Y and Z turned over, squares half a unit,
        # across the axes other than the projection axis; colour 2 on odd squares for X and Y, even for Z.
        for axis, pair, odd_is_two in ((0, (1, 2), True), (1, (0, 2), True), (2, (0, 1), False)):
            made = procedurals.checker_rows(rows, axis)
            for i in range(-9, 10):
                for j in range(-9, 10):
                    point = (i * 0.071 + 0.003, j * 0.067 + 0.002, 0.0)
                    flipped = (point[0], -point[1], -point[2])
                    local = [2 * (sum(r[k] * flipped[k] for k in range(3)) + r[3]) for r in rows]
                    odd = (math.floor(local[pair[0]]) + math.floor(local[pair[1]])) & 1
                    self.assertEqual(colour(made, point), bool(odd) == odd_is_two, (axis, point))

    def test_cube_keeps_its_colours(self):
        rows = turned(0.4, -0.2, 0.5, (0.37, -0.21, 0.13))
        made = procedurals.checker_rows(rows, 0, cube=True)
        point = (0.11, 0.23, -0.05)
        flipped = (point[0], -point[1], -point[2])
        local = [2 * (sum(r[k] * flipped[k] for k in range(3)) + r[3]) for r in rows]
        odd = sum(math.floor(v) for v in local) & 1
        self.assertEqual(colour(made, point, cube=True), not odd)

    def test_axis_named_by_letter(self):
        rows = turned(0.3, 0.1, 0.4)
        self.assertEqual(procedurals.checker_rows(rows, 'x'), procedurals.checker_rows(rows, 0))
        self.assertEqual(procedurals.checker_rows(rows, 'Z'), procedurals.checker_rows(rows, 2))


if __name__ == '__main__':
    unittest.main()
