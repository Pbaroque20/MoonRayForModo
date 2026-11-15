"""Replicator copies over particles named by their particles' IDs (evaluated.assign_particle_ids, copy_key): Modo's
render cache numbers a replicator's copies by their place among the particles, which changes as particles are born and
die, so motion blur paired a copy at the shutter's ends with another particle (long wrong streaks). Named by particle
ID, each copy is paired with itself; copies over a mesh's points (no IDs given) keep their places as before."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import evaluated, motion, rdla  # noqa: E402


def segment():
    return {'vertices': [[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'faces': [[0, 1, 2]], 'face_varying': True,
            'normals': [[0, 0, 1]] * 3, 'uv_sets': []}


def surface(source, index, x, item='replicator035'):
    matrix = list(rdla.IDENTITY)
    matrix[12] = x
    return {'source_id': source, 'source_item': item, 'material': 'm', 'layers': [], 'visibility': [True] * 6,
            'matrix': matrix, 'instance_index': index, 'instanced': 1}


def reading(places, prototype='mesh027'):
    """A render cache reading of one prototype's copies at the given places, in the enumerator's order."""
    return {'prototypes': {'1': {'item': prototype, 'features': [], 'segments': [segment()]}},
            'surfaces': [surface(1, index, x) for index, x in enumerate(places)]}


def sample(data):
    return {'camera': {'identity': 'cam', 'matrix': list(rdla.IDENTITY), 'focal_mm': 50},
            'meshes': evaluated.meshes(data, {'m': {}}, []), 'lights': [], 'fps': 24}


# Particles A, B, C at the shutter's opening; B dies and D is born before the frame; A, C and D at its closing. Each
# moves 1 along x over the shutter.
OPEN = [('0.5', 0.0), ('0.25', 10.0), ('0.75', 20.0)]
FRAME = [('0.5', 0.5), ('0.75', 20.5), ('0.125', 30.5)]
CLOSE = [('0.5', 1.0), ('0.75', 21.0), ('0.125', 31.0)]


def moment(particles, ids=True):
    data = reading([x for _, x in particles])
    if ids:
        evaluated.assign_particle_ids(data, {'replicator035': [('mesh027', float(pid)) for pid, _ in particles]})
    return data


def blurred(ids):
    scene = sample(moment(FRAME, ids))
    motion.apply_motion(scene, sample(moment(OPEN, ids)), sample(moment(CLOSE, ids)), [-.25, .25])
    mesh = scene['meshes'][0]
    return {identity: (a[12], b[12]) for identity, a, b in zip(mesh['instance_ids'], mesh['instances'], mesh['instances_close'])}, scene


class ParticleIds(unittest.TestCase):
    def test_each_copy_gets_its_particle_s_id_by_its_place(self):
        data = moment(FRAME)
        self.assertEqual([s['particle_id'] for s in data['surfaces']], ['0.5', '0.75', '0.125'])
        self.assertEqual([evaluated.copy_key(s) for s in data['surfaces']], ['p0.5', 'p0.75', 'p0.125'])

    def test_copies_are_named_by_particle(self):
        meshes = evaluated.meshes(moment(FRAME), {'m': {}}, [])
        self.assertEqual(meshes[0]['instance_ids'], ['replicator035|p0.5', 'replicator035|p0.75', 'replicator035|p0.125'])

    def test_without_ids_copies_keep_their_places(self):
        meshes = evaluated.meshes(moment(FRAME, ids=False), {'m': {}}, [])
        self.assertEqual(meshes[0]['instance_ids'], ['replicator035|0', 'replicator035|1', 'replicator035|2'])

    def test_each_copy_blurs_along_its_own_particle(self):
        paths, scene = blurred(ids=True)
        self.assertEqual(paths['replicator035|p0.5'], (0.0, 1.0))
        self.assertEqual(paths['replicator035|p0.75'], (20.0, 21.0))
        # Born after the shutter opened: held where it is at the frame for the opening.
        self.assertEqual(paths['replicator035|p0.125'], (30.5, 31.0))
        self.assertNotIn('replicator035|p0.25', paths)  # dead by the frame
        self.assertTrue(any('come and go' in w for w in scene['warnings']))
        self.assertTrue(all(abs(b - a) <= 1.0 for a, b in paths.values()))

    def test_by_place_a_copy_blurred_toward_another_particle(self):
        # What it was: the second copy opened on B and closed on C.
        paths, _ = blurred(ids=False)
        self.assertEqual(paths['replicator035|1'], (10.0, 21.0))

    def test_several_prototypes_are_numbered_apart(self):
        data = {'prototypes': {'1': {'item': 'mesh027', 'features': [], 'segments': [segment()]},
                               '2': {'item': 'mesh031', 'features': [], 'segments': [segment()]}},
                'surfaces': [surface(1, 0, 0.0), surface(2, 0, 1.0), surface(1, 1, 2.0)]}
        rows = [('mesh027', 0.1), ('mesh031', 0.2), ('mesh027', 0.3)]
        self.assertEqual(evaluated.assign_particle_ids(data, {'replicator035': rows}), 3)
        self.assertEqual([s['particle_id'] for s in data['surfaces']], ['0.1', '0.2', '0.3'])

    def test_copies_numbered_on_from_another_replicator(self):
        # Two replicators of one prototype: Modo numbers the second's copies on from the first's (0-2, then 3-4).
        data = {'prototypes': {'1': {'item': 'mesh027', 'features': [], 'segments': [segment()]}},
                'surfaces': [surface(1, i, float(i), item='replicator099') for i in range(3)]
                            + [surface(1, 4, 4.0), surface(1, 3, 3.0)]}
        evaluated.assign_particle_ids(data, {'replicator035': [('mesh027', 0.3), ('mesh027', 0.9)]})
        self.assertEqual([s.get('particle_id') for s in data['surfaces']], [None, None, None, '0.9', '0.3'])

    def test_a_group_s_meshes_take_the_group_s_ids(self):
        data = {'prototypes': {'1': {'item': 'wheel', 'features': [], 'segments': [segment()]},
                               '2': {'item': 'body', 'features': [], 'segments': [segment()]}},
                'surfaces': [surface(1, 0, 0.0), surface(2, 0, 0.0), surface(1, 1, 5.0), surface(2, 1, 5.0)]}
        parents = {'wheel': 'car', 'body': 'car'}
        owner = lambda item, known: item if item in known else (parents.get(item) if parents.get(item) in known else None)
        evaluated.assign_particle_ids(data, {'replicator035': [('car', 0.4), ('car', 0.6)]}, owner)
        self.assertEqual([s['particle_id'] for s in data['surfaces']], ['0.4', '0.4', '0.6', '0.6'])

    def test_copies_that_cannot_be_told_apart_keep_their_places(self):
        for rows in ([('mesh027', 0.5), ('mesh027', 0.5), ('mesh027', 0.7)],  # two particles of one ID
                     [('mesh027', 0.5), ('mesh027', 0.6)],  # fewer particles than copies
                     [('mesh027', 0.5), ('mesh027', 0.6), ('mesh027', 0.7), ('mesh027', 0.8)],  # more
                     [('other', 0.5), ('other', 0.6), ('other', 0.7)]):  # not this prototype's
            data = moment(FRAME, ids=False)
            self.assertEqual(evaluated.assign_particle_ids(data, {'replicator035': rows}), 0)
            self.assertFalse(any('particle_id' in s for s in data['surfaces']))

    def test_copies_of_other_items_are_left_alone(self):
        data = moment(FRAME, ids=False)
        data['surfaces'].append(surface(1, 0, 3.0, item='replicator099'))
        evaluated.assign_particle_ids(data, {'replicator035': [('mesh027', float(p)) for p, _ in FRAME]})
        self.assertNotIn('particle_id', data['surfaces'][-1])
        self.assertEqual(evaluated.copy_key(data['surfaces'][-1]), '0')

    def test_variation_by_particle_follows_the_particle(self):
        # Modo's Variation Texture by Particle: a copy's number from its identity, now its particle's.
        from moonray_modo import occlusion
        at_frame = evaluated.meshes(moment(FRAME), {'m': {}}, [])[0]
        at_close = evaluated.meshes(moment(list(reversed(CLOSE))), {'m': {}}, [])[0]
        number = dict(zip(at_frame['instance_ids'], map(occlusion.number, at_frame['instance_ids'])))
        self.assertEqual({i: occlusion.number(i) for i in at_close['instance_ids']}, number)


if __name__ == '__main__':
    unittest.main()
