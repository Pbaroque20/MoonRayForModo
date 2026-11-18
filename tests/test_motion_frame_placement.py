"""Where each moving part stands at the frame, kept with the shutter's ends and handed to MoonLightIPR (form 'U'): a car's
wheels turned a third of a turn while the shutter was open, and MoonLightIPR, holding the frame's moment without motion
blur, blended their two ends number by number and showed them half their size; their spokes, turning about the axle
rather than their own origin, stood beside them once the turn was followed alone. The session shows the frame's own
placement at that moment, and blends each half of the shutter from it."""
import math
import pathlib
import struct
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
sys.path.insert(0, str(ROOT / 'tests'))
from moonray_modo import moonlightipr_scene  # noqa: E402
from moonray_modo.motion import apply_motion, IDENTITY  # noqa: E402
from test_moonlightipr import scene as packable  # noqa: E402


def turned(angle, x=0.0, z=0.0):
    """Turned about X by angle (degrees), at x, 0.3, z: as Modo keeps it, basis vectors in rows."""
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return [1, 0, 0, 0, 0, c, s, 0, 0, -s, c, 0, x, 0.3, z, 1]


def sample(wheel, copies):
    return {'camera': {'identity': 'cam', 'matrix': list(IDENTITY), 'focal_mm': 50},
            'meshes': [{'identity': 'rim|m|0', 'name': 'Rim', 'faces': [[0, 1, 2]], 'vertices': [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                        'material': 'm', 'matrix': wheel},
                       {'identity': 'tyre|m|0', 'name': 'Tyre', 'faces': [[0, 1, 2]], 'vertices': [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                        'material': 'm', 'instances': copies, 'instance_ids': ['tyre|-1', 'copy|0']},
                       {'identity': 'body|m|0', 'name': 'Body', 'faces': [[0, 1, 2]], 'vertices': [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                        'material': 'm', 'matrix': list(IDENTITY)}],
            'lights': []}


class KeptWithTheEnds(unittest.TestCase):
    def test_a_moving_part_and_each_moving_copy_keep_where_they_stand_at_the_frame(self):
        frame = sample(turned(0, z=-0.73), [turned(0, z=-0.73), turned(0, 1.6, -0.73)])
        apply_motion(frame, sample(turned(-60, z=-1.09), [turned(-60, z=-1.09), turned(-60, 1.6, -1.09)]),
                     sample(turned(60, z=-0.37), [turned(60, z=-0.37), turned(60, 1.6, -0.37)]), [-.25, .25])
        rim, tyre, body = frame['meshes']
        self.assertEqual(rim['matrix'], turned(-60, z=-1.09))
        self.assertEqual(rim['matrix_close'], turned(60, z=-0.37))
        self.assertEqual(rim['matrix_frame'], turned(0, z=-0.73))
        self.assertEqual(tyre['instances_frame'], [turned(0, z=-0.73), turned(0, 1.6, -0.73)])
        self.assertNotIn('matrix_frame', tyre)
        # What does not move has nothing more.
        self.assertNotIn('matrix_frame', body)


class PackedForMoonLightIPR(unittest.TestCase):
    def moving(self):
        held = packable()
        held['motion_steps'] = [-.25, .25]
        held['meshes'][0].update(instances=[turned(-60), turned(-60, 3.0)], instances_close=[turned(60), turned(60, 3.0)],
                                 instances_frame=[turned(0), turned(0, 3.0)])
        return held

    def test_each_instance_carries_its_place_at_the_frame_after_its_close(self):
        payload, _, _ = moonlightipr_scene.pack(self.moving(), 320, 180)
        self.assertEqual(payload[:4], b'MLSW')
        for opening, closing, frame in ((turned(-60), turned(60), turned(0)), (turned(-60, 3.0), turned(60, 3.0), turned(0, 3.0))):
            record = struct.pack('<12f', *moonlightipr_scene.transform(opening)) + struct.pack('<12f', *moonlightipr_scene.transform(closing)) \
                + struct.pack('<12f', *moonlightipr_scene.transform(frame))
            self.assertIn(record, payload)

    def test_a_placement_not_read_at_the_frame_is_put_between_its_ends(self):
        held = self.moving()
        held['meshes'][0].pop('instances_frame')
        payload, _, _ = moonlightipr_scene.pack(held, 320, 180)
        between = [(a + b) / 2 for a, b in zip(moonlightipr_scene.transform(turned(-60)), moonlightipr_scene.transform(turned(60)))]
        self.assertIn(struct.pack('<12f', *moonlightipr_scene.transform(turned(60))) + struct.pack('<12f', *between), payload)

    def test_the_frame_falls_where_the_shutter_says(self):
        # A shutter opening at the frame: the frame is its opening (0), written after the closing camera.
        held = self.moving()
        held['motion_steps'] = [0.0, .5]
        late, _, _ = moonlightipr_scene.pack(held, 320, 180)
        centred, _, _ = moonlightipr_scene.pack(self.moving(), 320, 180)
        self.assertEqual(len(late), len(centred))
        self.assertIn(struct.pack('<f', 0.0), late)
        differing = [i for i in range(len(late)) if late[i] != centred[i]]
        self.assertTrue(differing)
        # Only the moment differs (the four bytes of one float).
        self.assertLessEqual(max(differing) - min(differing), 3)


if __name__ == '__main__':
    unittest.main()
