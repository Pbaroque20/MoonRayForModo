"""Solo in the preview (solo.py): a graph node shown as a light of its colour on its material's meshes, its displacement
kept; only one material's meshes; only the selected meshes; nothing changed with solo off, and listeners told."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import nodes, solo  # noqa: E402


def scene():
    graph = nodes.new('DwaBaseMaterial', {'albedo': [1, 0, 0]})
    graph['nodes']['noise'] = {'type': 'NoiseMap_v2', 'parameters': {}, 'inputs': {}, 'position': [0, 0]}
    graph['nodes']['push'] = {'type': 'VectorDisplacement', 'parameters': {}, 'inputs': {'vector': 'noise'}, 'position': [0, 0]}
    graph['nodes']['surface']['inputs']['albedo'] = 'noise'
    graph['displacement'] = 'push'
    return {'materials': {'Sea': {'base_layer_id': 'mat1', 'node_graph': graph, 'node_override': True, 'native_shader': 'DwaBaseMaterial'},
                          'Red': {'base_layer_id': 'mat2', 'color': [1, 0, 0]}},
            'meshes': [{'name': 'Plane', 'identity': 'mesh1|0|Texture', 'material': 'Sea'},
                       {'name': 'Ball', 'identity': 'mesh2|0|Texture', 'material': 'Red'},
                       {'name': 'Both', 'identity': 'mesh3|0|Texture', 'material': 'Red', 'face_materials': ['Red', 'Sea']}]}


class Solo(unittest.TestCase):
    def tearDown(self):
        solo.clear()

    def test_off_leaves_the_scene_as_it_is(self):
        held = scene()
        self.assertIs(solo.apply(held), held)

    def test_a_node_is_shown_as_a_light_of_its_colour_with_the_displacement_kept(self):
        solo.solo_node('mat1', 'noise')
        shown = solo.apply(scene())
        sea = shown['materials']['Sea']
        root = sea['node_graph']['nodes'][sea['node_graph']['root']]
        self.assertEqual(root['type'], 'DwaEmissiveMaterial')
        self.assertEqual(root['inputs'], {'emission': 'noise'})
        self.assertEqual(sea['node_graph']['displacement'], 'push')
        self.assertEqual(sea['native_shader'], 'DwaEmissiveMaterial')
        nodes.validate(sea['node_graph'])
        self.assertEqual(len(shown['meshes']), 3)
        self.assertEqual(shown['materials']['Red'], scene()['materials']['Red'])

    def test_a_material_node_is_shown_as_that_material(self):
        held = scene()
        held['materials']['Sea']['node_graph']['nodes']['other'] = {'type': 'DwaMetalMaterial', 'parameters': {}, 'inputs': {}, 'position': [0, 0]}
        solo.solo_node('mat1', 'other')
        self.assertEqual(solo.apply(held)['materials']['Sea']['node_graph']['root'], 'other')

    def test_a_material_shows_only_the_meshes_that_wear_it(self):
        solo.solo_materials(['mat1'])
        self.assertEqual([m['name'] for m in solo.apply(scene())['meshes']], ['Plane', 'Both'])

    def test_selected_meshes_alone(self):
        solo.solo_meshes(['mesh2'])
        self.assertEqual([m['name'] for m in solo.apply(scene())['meshes']], ['Ball'])

    def test_listeners_are_told(self):
        told = []
        solo.LISTENERS.append(lambda: told.append(solo.current()))
        try:
            solo.solo_meshes(['mesh1'], 'Plane')
            solo.clear()
        finally:
            solo.LISTENERS.pop()
        self.assertEqual([t and t['label'] for t in told], ['Plane', None])


if __name__ == '__main__':
    unittest.main()
