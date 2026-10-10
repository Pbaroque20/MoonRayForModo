"""OpenPBR and glTF surfaces of a MaterialX file are read as the Standard Surface they come closest to."""
import sys
import tempfile
import types
import unittest
from pathlib import Path

for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import materialx

OPENPBR = """<?xml version="1.0"?>
<materialx version="1.39">
  <image name="grain" type="color3"><input name="file" type="filename" value="grain.png" /></image>
  <open_pbr_surface name="S" type="surfaceshader">
    <input name="base_color" type="color3" nodename="grain" />
    <input name="base_metalness" type="float" value="0.25" />
    <input name="specular_roughness" type="float" value="0.4" />
    <input name="specular_ior" type="float" value="1.6" />
    <input name="coat_weight" type="float" value="0.5" />
    <input name="coat_roughness" type="float" value="0.05" />
    <input name="fuzz_weight" type="float" value="0.3" />
    <input name="fuzz_color" type="color3" value="0.9, 0.8, 0.7" />
    <input name="transmission_weight" type="float" value="0.2" />
    <input name="emission_luminance" type="float" value="2.0" />
    <input name="emission_color" type="color3" value="1, 0.5, 0.25" />
    <input name="geometry_opacity" type="float" value="0.75" />
    <input name="coat_darkening" type="float" value="0.5" />
    <input name="thin_film_thickness" type="float" value="0.5" />
  </open_pbr_surface>
  <surfacematerial name="M" type="material"><input name="surfaceshader" type="surfaceshader" nodename="S" /></surfacematerial>
</materialx>
"""
GLTF = """<?xml version="1.0"?>
<materialx version="1.38">
  <gltf_pbr name="S" type="surfaceshader">
    <input name="base_color" type="color3" value="0.2, 0.4, 0.8" />
    <input name="metallic" type="float" value="0" />
    <input name="roughness" type="float" value="0.35" />
    <input name="ior" type="float" value="1.45" />
    <input name="emissive" type="color3" value="0.1, 0.2, 0.3" />
    <input name="clearcoat" type="float" value="1" />
    <input name="clearcoat_roughness" type="float" value="0.1" />
    <input name="alpha" type="float" value="1" />
    <input name="occlusion" type="float" value="0.5" />
  </gltf_pbr>
  <surfacematerial name="M" type="material"><input name="surfaceshader" type="surfaceshader" nodename="S" /></surfacematerial>
</materialx>
"""
PLAIN_GLTF = """<?xml version="1.0"?>
<materialx version="1.38">
  <gltf_pbr name="S" type="surfaceshader" />
  <surfacematerial name="M" type="material"><input name="surfaceshader" type="surfaceshader" nodename="S" /></surfacematerial>
</materialx>
"""


class Surfaces(unittest.TestCase):
    def read(self, text):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'm.mtlx'
            path.write_text(text)
            graph = materialx.read(path)
        return graph, graph['nodes'][graph['root']]

    def test_an_openpbr_surface_becomes_a_moonray_material(self):
        graph, root = self.read(OPENPBR)
        self.assertEqual(root['type'], 'DwaBaseMaterial')
        held = root['parameters']
        self.assertEqual((held['metallic'], held['roughness'], held['refractive_index']), (0.25, 0.4, 1.6))
        self.assertEqual((held['clearcoat'], held['clearcoat_roughness'], held['fuzz'], held['transmission']), (0.5, 0.05, 0.3, 0.2))
        self.assertEqual(held['fuzz_albedo'], [0.9, 0.8, 0.7])
        self.assertEqual(held['presence'], 0.75)
        # The colour comes from the file's image, and the light it gives off is its colour times its strength.
        self.assertEqual(graph['nodes'][root['inputs']['albedo']]['type'], 'image')
        glow = graph['nodes'][root['inputs']['emission']]
        self.assertEqual((glow['type'], glow['parameters']['in1'], glow['parameters']['in2']), ('multiply', [1.0, 0.5, 0.25], [2.0] * 3))

    def test_what_has_no_counterpart_is_left_out_and_named(self):
        graph, _ = self.read(OPENPBR)
        self.assertEqual(sorted(graph['materialx_left_out']), ['S: coat_darkening', 'S: thin_film_thickness'])
        graph, _ = self.read(GLTF)
        self.assertEqual(graph['materialx_left_out'], ['S: occlusion'])

    def test_a_gltf_surface_becomes_a_moonray_material(self):
        graph, root = self.read(GLTF)
        held = root['parameters']
        self.assertEqual(held['albedo'], [0.2, 0.4, 0.8])
        self.assertEqual((held['metallic'], held['roughness'], held['refractive_index'], held['clearcoat'], held['clearcoat_roughness']), (0.0, 0.35, 1.45, 1.0, 0.1))
        # glTF has a colour of light given off and no strength for it: the colour is the light.
        self.assertEqual(held['emission'], [0.1, 0.2, 0.3])

    def test_a_gltf_surface_with_nothing_set_starts_as_gltf_does(self):
        _, root = self.read(PLAIN_GLTF)
        self.assertEqual((root['parameters']['metallic'], root['parameters']['roughness'], root['parameters']['albedo']), (1.0, 1.0, [1.0, 1.0, 1.0]))
        self.assertEqual(root['parameters']['emission'], [0, 0, 0])


if __name__ == '__main__':
    unittest.main()
