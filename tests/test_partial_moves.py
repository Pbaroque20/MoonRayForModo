"""A move after the scene was read is never a whole reading again (incremental.classify): any item moved (a group, a
locator, the root a car hangs from) has every mesh that stands with its item asked where it now is, instances among
them; only copies that stand with no item of their own (a replicator's), meshes a deformer bends and meshes textured by
a projection are read again from Modo. A car with instances had every move of a part read whole, 28 s."""
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import incremental  # noqa: E402

HERE = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 2, 0, 0, 1]
THERE = HERE[:12] + [7, 0, 0, 1]


def host(where):
    """The plugin's host module, which needs Modo: only where an item stands is asked of it."""
    fake = ModuleType('moonray_modo.host')
    fake.world_matrix = lambda item: where.get(item.id, HERE)
    return mock.patch.dict(sys.modules, {'moonray_modo.host': fake})


def item(identity, kind, owners=(), deforms=()):
    graphs = {'xfrmCore': list(owners), 'deformers': list(deforms)}
    return SimpleNamespace(id=identity, type=kind, children=lambda recursive=False: [],
                           itemGraph=lambda name: SimpleNamespace(forward=lambda: graphs.get(name, [])))


def scene(items, deform=(), kinds=None):
    held = {i.id: i for i in items}
    kinds = kinds or {}

    def listed(kind, superType=False):
        if kind == 'deform':
            return list(deform)
        return kinds.get(kind, [])
    return SimpleNamespace(item=lambda identity: held[identity], items=listed)


class Standing(unittest.TestCase):
    def test_meshes_and_instances_stand_with_their_items(self):
        snapshot = {'meshes': [
            {'identity': 'body|paint|0', 'source_item': 'body', 'matrix': HERE},
            {'identity': 'wheel|rubber|0', 'source_item': 'wheel', 'matrix': HERE, 'instances': [HERE, THERE],
             'instance_ids': ['wheel|0', 'wheelInst|0']}]}
        with host({'wheelInst': THERE}):
            followed, loose = incremental.standing(scene([item('body', 'mesh'), item('wheel', 'mesh'), item('wheelInst', 'meshInst')]), snapshot)
        self.assertTrue(followed)
        self.assertEqual(loose, set())

    def test_a_replicators_copies_are_loose(self):
        snapshot = {'meshes': [
            {'identity': 'body|paint|0', 'source_item': 'body', 'matrix': HERE},
            {'identity': 'rivet|steel|0', 'source_item': 'rivets', 'matrix': HERE, 'instances': [THERE, THERE],
             'instance_ids': ['rivets|0', 'rivets|1']}]}
        with host({}):
            followed, loose = incremental.standing(scene([item('body', 'mesh'), item('rivets', 'replicator')]), snapshot)
        self.assertTrue(followed)
        self.assertEqual(loose, {'rivets'})
        with host({}):
            self.assertFalse(incremental.stands_with_items(scene([item('body', 'mesh'), item('rivets', 'replicator')]), snapshot))


class Moves(unittest.TestCase):
    def setUp(self):
        self.group = item('wheels', 'groupLocator')
        self.move = item('move', 'translation', owners=[self.group])
        self.cache = {'_evaluated_data': {}, '_item_transforms': True, 'materials': {},
                      'meshes': [{'identity': 'wheel|rubber|0', 'source_item': 'wheel', 'material': 'rubber'}]}

    def test_moving_a_group_follows_its_meshes(self):
        found = scene([self.group, self.move])
        self.assertEqual(incremental.classify(found, {'move'}, self.cache), 'transforms')

    def test_moving_with_a_replicator_reads_its_copies_again(self):
        self.cache['_loose_items'] = {'rivets'}
        found = scene([self.group, self.move])
        self.assertEqual(incremental.classify(found, {'move'}, self.cache), {'dirty_meshes': {'rivets'}, 'placements': True})

    def test_moving_with_a_deformer_reads_what_it_bends(self):
        body = item('body', 'mesh')
        bend = item('bend', 'deformBend', deforms=[item('falloff', 'falloff', deforms=[body])])
        found = scene([self.group, self.move, body, bend], deform=[bend])
        self.assertEqual(incremental.classify(found, {'move'}, self.cache), {'dirty_meshes': {'body'}, 'placements': True})

    def test_unfollowed_meshes_keep_the_whole_reading(self):
        self.cache['_item_transforms'] = False
        self.assertFalse(incremental.classify(scene([self.group, self.move]), {'move'}, self.cache))


class Refresh(unittest.TestCase):
    def test_instances_are_asked_by_their_item_and_loose_copies_keep_their_places(self):
        snapshot = {'meshes': [
            {'identity': 'wheel|rubber|0', 'source_item': 'wheel', 'matrix': HERE, 'instances': [HERE, HERE],
             'instance_ids': ['wheel|0', 'wheelInst|0']},
            {'identity': 'rivet|steel|0', 'source_item': 'rivets', 'matrix': HERE}]}
        found = scene([item('wheel', 'mesh'), item('wheelInst', 'meshInst'), item('rivets', 'replicator')],
                      kinds={'meshInst': ['wheelInst']})
        with host({'wheel': THERE, 'wheelInst': THERE, 'rivets': THERE}):
            incremental.refresh_transforms(found, snapshot, None, loose={'rivets'})
        self.assertEqual(snapshot['meshes'][0]['instances'], [THERE, THERE])
        self.assertEqual(snapshot['meshes'][1]['matrix'], HERE)

    def test_an_unmoved_mesh_keeps_its_matrix_to_the_last_digit(self):
        # Modo's render cache and the item's world matrix differ in their last digits: a new matrix for each would have
        # the renderer take every mesh for edited.
        read = [v + 1e-9 for v in HERE]
        snapshot = {'meshes': [{'identity': 'body|paint|0', 'source_item': 'body', 'matrix': read},
                               {'identity': 'door|paint|0', 'source_item': 'door', 'matrix': HERE}]}
        found = scene([item('body', 'mesh'), item('door', 'mesh')], kinds={'chanModify': ['cm']})
        with host({'door': THERE}):
            incremental.refresh_transforms(found, snapshot, None)
        self.assertIs(snapshot['meshes'][0]['matrix'], read)
        self.assertEqual(snapshot['meshes'][1]['matrix'], THERE)


if __name__ == '__main__':
    unittest.main()
