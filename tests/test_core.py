import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import rdla, native


def scene():
    return {'camera': {'matrix': rdla.IDENTITY, 'focal_mm': 50, 'film_mm': 36},
            'meshes': [{'name': 'test', 'vertices': [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                        'faces': [[0, 1, 2]], 'material': ''}]}


class CoreTests(unittest.TestCase):
    def test_glass_separates_transmission_and_presence(self):
        data = scene()
        data['materials'] = {'': {'color':[.5,.5,.5], 'transmission':.8, 'presence':.7,
                                  'ior':1.45, 'roughness':.1, 'refraction_roughness':.25,
                                  'transmission_color':[.2,.9,.3]}}
        text = rdla.scene_text(data)
        self.assertIn('ModoGlassMaterial(', text)
        self.assertIn('["transmission"] = 0.8', text)
        self.assertIn('["presence"] = 0.7', text)
        self.assertIn('["refractionRoughness"] = 0.25', text)
        self.assertNotIn('useSpecularWorkflow', text)
        data['materials']['']['transmission'] = 0
        data['materials']['']['presence'] = 1
        self.assertNotIn('ModoGlassMaterial(', rdla.scene_text(data))

    def test_transmission_texture_selects_glass_even_at_zero_base_amount(self):
        data = scene()
        data['materials'] = {'': {'color':[1,1,1], 'textures': {'tranAmt': {'path':'amount.png'}}}}
        with patch('moonray_modo.textures.prepare', return_value='amount.tx'):
            text = rdla.scene_text(data)
        self.assertIn('ModoGlassMaterial(', text)
        self.assertIn('["transmission"] = bind(ModoTextureMap(', text)

    def test_image_bindings_and_safe_texture_paths(self):
        data = scene()
        data['materials'] = {'': {'color': [1,1,1], 'textures': {
            'diffCol': {'path': 'source.png', 'srgb': True},
            'rough': {'path': 'roughness.png', 'srgb': False}}}}
        with patch('moonray_modo.textures.prepare', return_value='C:/cache/a"b.tx') as prepare:
            text = rdla.scene_text(data)
        self.assertEqual(prepare.call_count, 2)
        self.assertIn('["diffuseColor"] = bind(ModoTextureMap(', text)
        self.assertIn('["roughness"] = bind(ModoTextureMap(', text)
        self.assertIn('a\\"b.tx', text)

    def test_unknown_image_effect_rejected(self):
        data = scene()
        data['materials'] = {'': {'color': [1,1,1], 'textures': {'unknown': {'path': 'bad.png'}}}}
        with self.assertRaisesRegex(ValueError, 'Unsupported image effect'):
            rdla.scene_text(data)

    def test_aovs_are_explicit_and_only_emitted_for_exr(self):
        data = scene()
        data['aovs'] = ['depth', 'normal', 'diffuse_direct']
        self.assertNotIn('RenderOutput(', rdla.scene_text(data))
        text = rdla.scene_text(data, output_file='passes.exr')
        self.assertEqual(text.count('RenderOutput('), 4)
        self.assertIn('["state_variable"] = 2', text)
        self.assertIn('["lpe"] = "diffuse"', text)
        data['aovs'] = ['not-supported']
        with self.assertRaises(ValueError):
            rdla.scene_text(data, output_file='passes.exr')

    def test_material_parts_preserve_one_mesh(self):
        data = scene()
        data['materials'] = {'red': {'color': [1, 0, 0]}}
        data['meshes'][0]['faces'] = [[0, 1, 2], [2, 1, 0]]
        data['meshes'][0]['face_materials'] = ['red', '']
        text = rdla.scene_text(data)
        self.assertEqual(text.count('RdlMeshGeometry('), 1)
        self.assertIn('["part_face_indices"] = {0, 1}', text)
        self.assertIn('{geometry, "part0", materials["red"]', text)

    def test_uv_and_normal_corner_counts_are_checked(self):
        data = scene()
        data['meshes'][0]['uvs'] = [[0, 0]]
        with self.assertRaises(ValueError):
            rdla.scene_text(data)

    def test_render_bounces_reach_scene_variables(self):
        data = scene()
        data['render_settings'] = {'max_depth': 9, 'max_diffuse_depth': 4}
        text = rdla.scene_text(data)
        self.assertIn('["max_depth"] = 9', text)
        self.assertIn('["max_diffuse_depth"] = 4', text)

    def test_subdivision_is_opt_in_for_polygon_meshes(self):
        data = scene()
        self.assertIn('["is_subd"] = false', rdla.scene_text(data))
        data['meshes'][0]['subdivision'] = True
        data['meshes'][0]['subdivision_level'] = 3
        exported = rdla.scene_text(data)
        self.assertIn('["is_subd"] = true', exported)
        self.assertIn('["mesh_resolution"] = 8', exported)
        self.assertIn('["shadow_terminator_fix"] = 1', exported)

    def test_subdivision_detail_is_bounded(self):
        data = scene()
        for level in (0, 6, 1.5, True):
            data['meshes'][0]['subdivision_level'] = level
            with self.assertRaises(ValueError):
                rdla.scene_text(data)

    def test_non_finite_geometry_rejected(self):
        data = scene()
        data['meshes'][0]['vertices'][0][0] = float('nan')
        with self.assertRaises(ValueError):
            rdla.scene_text(data)

    def test_bad_indices_rejected(self):
        data = scene()
        data['meshes'][0]['faces'] = [[0, 1, 3]]
        with self.assertRaises(ValueError):
            rdla.scene_text(data)

    def test_bad_dimensions_rejected(self):
        with self.assertRaises(ValueError):
            rdla.scene_text(scene(), width=0)

    def test_utf8_names_and_lua_escaping(self):
        encoded = rdla.string('a"\\\n雪123')
        self.assertEqual(encoded, '"a\\"\\\\\\010\\233\\155\\170123"')
        self.assertNotIn('\n', encoded)

    def test_material_names_cannot_execute_lua(self):
        data = scene()
        data['materials'] = {'"); os.execute("bad") --': {'color': [1, 0, 0]}}
        text = rdla.scene_text(data)
        self.assertIn('materials["\\"); os.execute(\\"bad\\") --"]', text)

    def test_default_material_for_unknown_tag(self):
        data = scene()
        data['meshes'][0]['material'] = 'missing'
        self.assertIn('materials[""], lightSet', rdla.scene_text(data))

    def test_native_discovery_and_spaces_in_arguments(self):
        with tempfile.TemporaryDirectory(prefix='MoonRay test ') as name:
            base = pathlib.Path(name)
            runtime = base / 'blender.shared'
            runtime.mkdir()
            (runtime / 'moonray.exe').touch()
            self.assertEqual(native.find_runtime(base), runtime.resolve())
            args = native.arguments(base / 'scene test.rdla', base / 'final render.exr', 4)
            self.assertEqual(args[1], str((base / 'scene test.rdla').resolve()))
            self.assertEqual(args[3], str((base / 'final render.exr').resolve()))

    def test_missing_renderer_is_explicit(self):
        with tempfile.TemporaryDirectory() as name:
            with self.assertRaises(ValueError):
                native.find_runtime(name)

    def test_kit_config_is_valid_xml(self):
        for path in (ROOT / 'kit/MoonRayForModo').glob('*.cfg'):
            ET.parse(path)


if __name__ == '__main__':
    unittest.main()
