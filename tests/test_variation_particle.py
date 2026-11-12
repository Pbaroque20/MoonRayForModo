"""Modo's Variation Texture by Particle: each replica (each instance of a mesh) carries a number of its own, the same each
time, for MoonRay as an attribute of each instance and for MoonLightIPR in each instance's record; a mesh standing alone
carries one on its points. And the Gradient's Bump and Displacement Height (read as the Bump and Displacement channels
beneath) and Clip Distance (held at 0), as measured against Modo's renders. No Modo."""
import pathlib
import struct
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import gradients, moonlightipr_scene, occlusion, procedurals  # noqa: E402

IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
MAP = procedurals.VARIATION_PARTICLE_MAP


def moved(x):
    return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, 0, 0, 1]


def scene(read=True):
    layer = {'kind': 'gradient', 'gradient': {'input': '@vmap', 'vmap': MAP}} if read else {'kind': 'constant'}
    triangle = {'vertices': [(0, 0, 0), (1, 0, 0), (0, 1, 0)], 'faces': [(0, 1, 2)], 'material': 'm'}
    return {'materials': {'m': {'layers': [layer]}},
            'meshes': [dict(triangle, name='Rock', identity='Rock|m|0', evaluated_geometry=True,
                            instances=[moved(0), moved(2), moved(4)], instance_ids=['Rock|0', 'Rock|1', 'Rock|2']),
                       dict(triangle, name='Rock', identity='Rock|3|m|0', evaluated_geometry=True, matrix=moved(6)),
                       dict(triangle, name='Box', identity='Box')]}


class VariationParticle(unittest.TestCase):
    def test_each_replica_its_own(self):
        held = scene()
        occlusion.particles(held)
        instanced, alone, box = held['meshes']
        numbers = instanced['instance_variation']
        self.assertEqual(len(set(numbers)), 3)
        self.assertTrue(all(0.0 <= n <= 1.0 for n in numbers))
        self.assertEqual([row[-1] for row in instanced['instance_attributes']],
                         [{'name': MAP, 'type': 'float', 'value': n} for n in numbers])
        # The instancer carries them, not the mesh's points (which every instance would share).
        self.assertNotIn(MAP, instanced.get('point_attributes', {}))
        self.assertEqual(alone['instance_variation'], [occlusion.number('Rock|3')])
        self.assertEqual(alone['point_attributes'][MAP]['values'], [[occlusion.number('Rock|3')]] * 3)
        self.assertEqual(box['instance_variation'], [occlusion.number('Box')])
        again = scene()
        occlusion.particles(again)
        self.assertEqual(numbers, again['meshes'][0]['instance_variation'])

    def test_other_attributes_kept(self):
        held = scene()
        held['meshes'][0]['instance_attributes'] = [[{'name': 'Cd', 'type': 'color', 'value': [1, 0, 0]}], [], []]
        occlusion.particles(held)
        rows = held['meshes'][0]['instance_attributes']
        self.assertEqual(rows[0][0]['name'], 'Cd')
        self.assertEqual([len(row) for row in rows], [2, 1, 1])

    def test_not_asked(self):
        held = scene(False)
        occlusion.particles(held)
        self.assertTrue(all('instance_variation' not in m and 'point_attributes' not in m for m in held['meshes']))

    def test_moonlightipr_instances_carry_them(self):
        held = scene()
        occlusion.particles(held)
        held.update(camera={'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1, 5, 1], 'focal_mm': 50.0, 'film_mm': 36.0},
                    lights=[], environments=[])
        # The numbers are in the instances whatever the material: a plain one here.
        held['materials'] = {'m': {'color': [.5, .5, .5]}, '': {'color': [.5, .5, .5]}}
        payload, _, _ = moonlightipr_scene.pack(held, 64, 36, 0.0)
        self.assertEqual(payload[:4], b'MLSR')
        for number, x in zip(held['meshes'][0]['instance_variation'], (0, 2, 4)):
            self.assertIn(struct.pack('<f12f', number, *moonlightipr_scene.transform(moved(x))), payload)


class HeightsAndClip(unittest.TestCase):
    def test_tables(self):
        self.assertEqual(gradients.HEIGHTS, {'bumpHeight': 'bump', 'displaceHeight': 'displace'})
        self.assertEqual(gradients.HELD, {'clipDist': 0.0})


if __name__ == '__main__':
    unittest.main()
