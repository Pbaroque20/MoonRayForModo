"""Select Volume Here: a VDB volume is found where its grid is thick under the point, not anywhere in its box, through
the viewport's coarse copy of the grid, placed as its item is. No Modo."""
import pathlib
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))

from moonray_modo import volume_pick  # noqa: E402

N = 4


def grid_file():
    """A 4 x 4 x 4 grid filling the unit cube, thick (1) in its middle 2 x 2 x 2 and thin (0.01) elsewhere, the unit
    cube taken to [-0.5, 0.5] in the grid's space."""
    values = [1.0 if all(1 <= c <= 2 for c in (i, j, k)) else 0.01 for k in range(N) for j in range(N) for i in range(N)]
    unit = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -0.5, -0.5, -0.5, 1]
    path = pathlib.Path(tempfile.mkdtemp()) / 'ball.mlv'
    path.write_bytes(b'MLV1' + struct.pack('<3I', N, N, N) + struct.pack('<f', 1.0) + struct.pack('<16f', *unit)
                     + struct.pack('<%df' % len(values), *values))
    return path


def scene(offset=(0.0, 0.0, 0.0)):
    placed = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, offset[0], offset[1], offset[2], 1]
    # A camera at z 5 looking down -Z, its picture 2 units across at the volume's depth's start.
    camera = {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 5, 1], 'film_mm': 36.0, 'focal_mm': 36.0 * 5 / 2}
    return {'camera': camera, 'width': 100, 'height': 100, 'entities': [],
            'extra_geometry': [{'kind': 'vdb', 'identity': 'vdb1', 'name': 'Fire', 'file': 'fire.vdb', 'density_grid': 'density', 'matrix': placed}]}


class VolumePick(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch('moonray_modo.vdb_preview.coarse_file', return_value=grid_file())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_thick_middle_is_found(self):
        depth, identity, name = volume_pick.volume_at(scene(), 0.5, 0.5)
        self.assertEqual((identity, name), ('vdb1', 'Fire'))
        # The thick cells start a quarter in: z 0.25, 4.75 from the camera.
        self.assertAlmostEqual(depth, 4.75, delta=0.15)

    def test_thin_corners_of_the_box_are_not(self):
        # Through the box near its corner, where the grid is thin all the way.
        depth, waiting = volume_pick.volume_at(scene(), 0.5 + 0.45 / 2, 0.5 - 0.45 / 2)
        self.assertIsNone(depth)
        self.assertEqual(waiting, [])

    def test_placed_as_its_item_is(self):
        moved = scene(offset=(10.0, 0.0, 0.0))
        self.assertIsNone(volume_pick.volume_at(moved, 0.5, 0.5)[0])

    def test_one_still_being_read_is_said(self):
        with mock.patch('moonray_modo.vdb_preview.coarse_file', return_value=None):
            depth, waiting = volume_pick.volume_at(scene(), 0.5, 0.5)
        self.assertIsNone(depth)
        self.assertEqual(waiting, ['Fire'])


if __name__ == '__main__':
    unittest.main()
