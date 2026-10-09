"""What a MaterialX file names for adjusting becomes the imported material's own controls."""
import sys
import tempfile
import types
import unittest
from pathlib import Path

for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import materialx, nodes

DOCUMENT = """<?xml version="1.0"?>
<materialx version="1.38">
  <nodegraph name="NG">
    <constant name="UVScale_Base" type="float"><input name="value" type="float" value="3.0" /></constant>
    <constant name="PaintColor" type="color3"><input name="value" type="color3" value="0.5, 0.2, 0.1" /></constant>
    <texcoord name="node_texcoord_1" type="vector2"><input name="index" type="integer" value="0" /></texcoord>
    <multiply name="node_multiply_2" type="vector2">
      <input name="in1" type="vector2" nodename="node_texcoord_1" /><input name="in2" type="float" nodename="UVScale_Base" />
    </multiply>
    <image name="node_image_3" type="float" GLSLFX_usage="roughness">
      <input name="texcoord" type="vector2" nodename="node_multiply_2" /><input name="file" type="filename" value="rough.png" />
    </image>
    <image name="node_image_4" type="float" GLSLFX_usage="roughness">
      <input name="file" type="filename" value="rough.png" />
    </image>
    <add name="node_add_5" type="float">
      <input name="in1" type="float" nodename="node_image_3" /><input name="in2" type="float" nodename="node_image_4" />
    </add>
    <dot name="color_out" type="color3"><input name="in" type="color3" nodename="PaintColor" /></dot>
    <normal name="onthefly_1" type="vector3"><input name="space" type="string" value="world" /></normal>
    <output name="rough_output" type="float" nodename="node_add_5" />
    <output name="color_output" type="color3" nodename="color_out" />
    <output name="coat_normal_output" type="vector3" nodename="onthefly_1" />
  </nodegraph>
  <standard_surface name="SR" type="surfaceshader">
    <input name="base_color" type="color3" output="color_output" nodegraph="NG" />
    <input name="specular_roughness" type="float" output="rough_output" nodegraph="NG" />
    <input name="coat_normal" type="vector3" output="coat_normal_output" nodegraph="NG" />
  </standard_surface>
  <surfacematerial name="M" type="material"><input name="surfaceshader" type="surfaceshader" nodename="SR" /></surfacematerial>
</materialx>
"""


class Controls(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / 'm.mtlx'
        self.path.write_text(DOCUMENT)
        self.graph = materialx.read(self.path)

    def tearDown(self):
        self.folder.cleanup()

    def test_named_values_and_images_are_the_controls(self):
        found = {c['label']: c for c in self.graph['controls']}
        self.assertEqual(sorted(found), ['Paint Color', 'Roughness image', 'UV Scale Base'])
        self.assertEqual(found['UV Scale Base']['kind'], 'number')
        self.assertEqual(found['Paint Color']['kind'], 'color')
        # One picture read at two places is one control; the other place follows it.
        self.assertEqual(len(found['Roughness image']['also']), 1)

    def test_the_default_normal_wired_in_is_left_out(self):
        root = self.graph['nodes'][self.graph['root']]
        self.assertNotIn('independent_clearcoat_normal', root['inputs'])
        self.assertFalse(root['parameters']['use_independent_clearcoat_normal'])

    def test_uvs_scaled_by_nodes_are_recognised(self):
        wired = [n for n in self.graph['nodes'].values() if n['type'] == 'image' and 'texcoord' in n.get('inputs', {})]
        self.assertEqual(len(wired), 1)
        self.assertEqual(nodes.wired_descriptor(self.graph, wired[0])['uv_matrix'], [3.0, 0.0, 0.0, 0.0, 3.0, 0.0])

    def test_the_graph_is_set_out_from_its_output_back(self):
        places = {key: node['position'] for key, node in self.graph['nodes'].items()}
        root = places[self.graph['root']]
        self.assertTrue(all(place[0] <= root[0] for place in places.values()))
        self.assertGreater(len({place[0] for place in places.values()}), 2)


if __name__ == '__main__':
    unittest.main()
