"""A mesh read at the shutter's ends is the frame's surface when its points match one for one and its faces are the
same, listed in another order or from another corner, or its quads cut along the other diagonal (motion.same_surface):
Modo's render cache lists a bending mesh's polygons in another order at the shutter's close, which refused its blur.
Readings for MoonLightIPR are undisplaced (host.by_engine), and Displacement layers are then kept in the materials."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import motion  # noqa: E402

POINTS = [[0, 0, 0]] * 8
QUADS = [[0, 1, 3], [2, 3, 1], [4, 5, 7], [6, 7, 5]]


class SameSurface(unittest.TestCase):
    def test_the_same_faces(self):
        self.assertTrue(motion.same_surface({'faces': QUADS, 'vertices': POINTS}, {'faces': QUADS, 'vertices': POINTS}))

    def test_faces_in_another_order_or_from_another_corner(self):
        shuffled = [[5, 7, 4], [7, 5, 6], [1, 3, 0], [2, 3, 1]]
        self.assertTrue(motion.same_surface({'faces': shuffled, 'vertices': POINTS}, {'faces': QUADS, 'vertices': POINTS}))

    def test_quads_cut_along_the_other_diagonal(self):
        flipped = [[0, 1, 2], [0, 2, 3], [4, 5, 7], [6, 7, 5]]
        self.assertTrue(motion.same_surface({'faces': flipped, 'vertices': POINTS}, {'faces': QUADS, 'vertices': POINTS}))

    def test_another_surface_is_not(self):
        other = [[0, 1, 4], [2, 3, 1], [4, 5, 7], [6, 7, 5]]
        self.assertFalse(motion.same_surface({'faces': other, 'vertices': POINTS}, {'faces': QUADS, 'vertices': POINTS}))
        self.assertFalse(motion.same_surface({'faces': QUADS, 'vertices': POINTS[:7]}, {'faces': QUADS, 'vertices': POINTS}))
        self.assertFalse(motion.same_surface({'faces': QUADS[:2], 'vertices': POINTS}, {'faces': QUADS, 'vertices': POINTS}))

    def test_face_materials_follow_their_faces(self):
        shuffled = [[4, 5, 7], [6, 7, 5], [0, 1, 3], [2, 3, 1]]
        a = {'faces': QUADS, 'face_materials': ['a', 'a', 'b', 'b']}
        b = {'faces': shuffled, 'face_materials': ['b', 'b', 'a', 'a']}
        self.assertEqual(motion.face_values(a, 'face_materials'), motion.face_values(b, 'face_materials'))


class ReadingByEngine(unittest.TestCase):
    def test_moonlightipr_reads_undisplaced(self):
        import types
        for name in ('lx', 'lxu', 'lxifc', 'modo'):
            sys.modules.setdefault(name, types.ModuleType(name))
        try:
            from moonray_modo import host
        except Exception as exc:
            self.skipTest('host needs Modo: %s' % exc)
        self.assertTrue(host.modo_displaces())
        with host.by_engine('moonlightipr'):
            self.assertFalse(host.modo_displaces())
        with host.by_engine('moonray'):
            self.assertTrue(host.modo_displaces())
        self.assertTrue(host.modo_displaces())


if __name__ == '__main__':
    unittest.main()
