"""The graph editor's presets: what is kept of a graph, the files, and what comes back. No Modo."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import node_presets as presets


def graph():
    return {'version': 1, 'root': 'surface', 'displacement': 'bump', 'overrides': [{'name': 'Layer', 'node': 'surface'}],
            'nodes': {'surface': {'type': 'DwaBaseMaterial', 'parameters': {'roughness': .4}, 'inputs': {'albedo': 'hsv'}, 'position': [300, 50]},
                      'hsv': {'type': 'ColorCorrectHsvMap', 'parameters': {}, 'inputs': {'input': 'img'}, 'position': [100, 0]},
                      'img': {'type': 'image', 'parameters': {'file': 'C:/a.png'}, 'inputs': {}, 'position': [-100, 0]},
                      'bump': {'type': 'NormalDisplacement', 'parameters': {}, 'inputs': {}, 'position': [0, 200]}}}


class CaptureTests(unittest.TestCase):
    def test_selection_keeps_only_the_wires_between_its_nodes(self):
        preset = presets.capture(graph(), ['hsv', 'surface'])
        self.assertEqual(preset['kind'], presets.SELECTION)
        kept = preset['graph']['nodes']
        self.assertEqual(sorted(kept), ['hsv', 'surface'])
        self.assertEqual(kept['surface']['inputs'], {'albedo': 'hsv'})
        self.assertEqual(kept['hsv']['inputs'], {})
        self.assertNotIn('root', preset['graph'])

    def test_network_keeps_everything(self):
        preset = presets.capture(graph())
        self.assertEqual(preset['kind'], presets.NETWORK)
        self.assertEqual(presets.network_of(preset), graph())

    def test_the_graph_itself_is_left_alone(self):
        original = graph()
        preset = presets.capture(original, ['hsv'])
        preset['graph']['nodes']['hsv']['parameters']['x'] = 1
        self.assertEqual(original, graph())


class AddedToTests(unittest.TestCase):
    def test_new_identities_their_wires_and_centred_on_the_point(self):
        target = {'version': 1, 'root': 'surface', 'nodes': {'surface': {'type': 'DwaBaseMaterial'}}}
        made = presets.added_to(target, presets.capture(graph(), ['hsv', 'img']), (500, 500))
        self.assertEqual(len(made), 2)
        self.assertEqual(len(target['nodes']), 3)
        self.assertEqual(target['root'], 'surface')
        hsv = next(target['nodes'][i] for i in made if target['nodes'][i]['type'] == 'ColorCorrectHsvMap')
        img = next(i for i in made if target['nodes'][i]['type'] == 'image')
        self.assertEqual(hsv['inputs'], {'input': img})
        self.assertEqual(hsv['position'], [600, 500])
        self.assertEqual(target['nodes'][img]['position'], [400, 500])

    def test_the_same_preset_twice_makes_two_of_each(self):
        target = {'version': 1, 'nodes': {}}
        preset = presets.capture(graph(), ['img'])
        presets.added_to(target, preset, (0, 0))
        presets.added_to(target, preset, (0, 0))
        self.assertEqual(len(target['nodes']), 2)

    def test_a_network_added_leaves_the_graphs_outputs_and_layers(self):
        target = {'version': 1, 'root': 'mine', 'nodes': {'mine': {'type': 'DwaBaseMaterial'}}}
        presets.added_to(target, presets.capture(graph()), (0, 0))
        self.assertEqual(target['root'], 'mine')
        self.assertNotIn('overrides', target)
        self.assertEqual(len(target['nodes']), 5)


class FileTests(unittest.TestCase):
    def setUp(self):
        held = tempfile.TemporaryDirectory()
        self.addCleanup(held.cleanup)
        patched = mock.patch.dict(os.environ, {'APPDATA': held.name})
        patched.start()
        self.addCleanup(patched.stop)

    def test_saved_listed_and_read_back(self):
        path = presets.save('Worn: metal/rust?', presets.capture(graph()))
        self.assertEqual(path.name, 'Worn_ metal_rust_.json')
        name, kind, found = presets.listed()[0]
        self.assertEqual((name, kind, found), ('Worn: metal/rust?', presets.NETWORK, path))
        self.assertEqual(presets.network_of(presets.read(path)), graph())

    def test_listed_by_name_whatever_the_case(self):
        for name in ('beta', 'Alpha', 'gamma'):
            presets.save(name, presets.capture(graph()))
        self.assertEqual([row[0] for row in presets.listed()], ['Alpha', 'beta', 'gamma'])

    def test_saving_a_name_again_replaces_it_and_leaves_no_staged_file(self):
        presets.save('One', presets.capture(graph()))
        presets.save('One', presets.capture(graph(), ['img']))
        self.assertEqual([row[1] for row in presets.listed()], [presets.SELECTION])
        self.assertEqual([p.name for p in presets.folder().iterdir()], ['One.json'])

    def test_a_file_that_is_no_preset_is_left_out(self):
        presets.save('Good', presets.capture(graph()))
        (presets.folder() / 'broken.json').write_text('{', encoding='utf-8')
        (presets.folder() / 'other.json').write_text(json.dumps({'format': 99}), encoding='utf-8')
        self.assertEqual([row[0] for row in presets.listed()], ['Good'])

    def test_no_folder_yet_is_no_presets(self):
        self.assertEqual(presets.listed(), [])

    def test_a_name_of_nothing_is_refused(self):
        for name in ('', '   ', '...'):
            with self.assertRaises(ValueError):
                presets.file_for(name)

    def test_read_refuses_what_it_cannot_use(self):
        path = presets.save('Good', presets.capture(graph()))
        path.write_text(json.dumps({'format': 1, 'kind': 'network', 'graph': {}}), encoding='utf-8')
        with self.assertRaises(ValueError):
            presets.read(path)


if __name__ == '__main__':
    unittest.main()
