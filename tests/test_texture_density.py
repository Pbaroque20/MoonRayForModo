"""How many texels across each texture its meshes can show on screen (texture_density), for XPU2's texture overflow mode:
a texture is followed from the materials its meshes wear to the maps that read it, its repeats from the maps' scale and
the UV placements they read through; its need is the widest of its meshes on screen over the repeats across it."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import texture_density  # noqa: E402

TEXT = r'''local materials = {}
ModoTextureMap("/modo/graph/0/1") {
  ["uv_affine"] = Vec4(100, 0, 0, 100),
}
ImageMap("/modo/graph/0/2") {
  ["texture"] = "C:\\cache\\tiles.tx",
  ["scale"] = Vec2(1, 1),
  ["input_texture_coordinates"] = bind(ModoTextureMap("/modo/graph/0/1"), Vec3(1, 1, 1)),
}
ImageMap("/modo/graph/0/3") {
  ["texture"] = "C:\\cache\\label.tx",
  ["scale"] = Vec2(2, 1),
}
materials["floor"] = DwaBaseMaterial("/modo/material/0") {
  ["albedo"] = bind(ImageMap("/modo/graph/0/2"), Rgb(1, 1, 1)),
}
materials["/modo/internal/1/0"] = DwaBaseMaterial("/modo/material/1") {
  ["albedo"] = bind(ImageMap("/modo/graph/0/3"), Rgb(1, 1, 1)),
}
materials["can"] = materials["/modo/internal/1/0"]
'''


def mesh(size, z):
    half = size / 2.0
    return {'vertices': [[-half, -half, 0], [half, -half, 0], [half, half, 0], [-half, half, 0]], 'faces': [[0, 1, 2, 3]],
            'uvs': [[0, 0], [1, 0], [1, 1], [0, 1]], 'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, z, 1]}


CAMERA = {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 10, 1], 'focal_mm': 50.0, 'film_mm': 36.0}


class TextureDensity(unittest.TestCase):
    def test_materials_reach_their_textures_and_repeats(self):
        found = texture_density.textures_of(TEXT)
        self.assertAlmostEqual(found['floor']['C:\\cache\\tiles.tx'], 100.0)
        # Through an alias, and the map's own scale.
        self.assertAlmostEqual(found['can']['C:\\cache\\label.tx'], 2.0)

    def test_a_texture_at_two_repeats_keeps_the_fewer(self):
        text = TEXT.replace('materials["floor"] = DwaBaseMaterial("/modo/material/0") {\n  ["albedo"] = bind(ImageMap("/modo/graph/0/2")',
                            'ImageMap("/modo/graph/0/4") {\n  ["texture"] = "C:\\\\cache\\\\tiles.tx",\n}\n'
                            'materials["floor"] = DwaBaseMaterial("/modo/material/0") {\n  ["roughness"] = bind(ImageMap("/modo/graph/0/4"), 1),\n'
                            '  ["albedo"] = bind(ImageMap("/modo/graph/0/2")')
        self.assertAlmostEqual(texture_density.textures_of(text)['floor']['C:\\cache\\tiles.tx'], 1.0)

    def test_a_mesh_small_on_screen_needs_fewer_texels(self):
        near = texture_density.needs(TEXT, [(mesh(8.0, 0.0), {'can'})], CAMERA, 1920)['C:\\cache\\label.tx']
        far = texture_density.needs(TEXT, [(mesh(8.0, -400.0), {'can'})], CAMERA, 1920)['C:\\cache\\label.tx']
        self.assertGreater(near, far)
        self.assertEqual(far, texture_density.SMALLEST)
        self.assertEqual(near & (near - 1), 0)   # a power of two
        # Tiled a hundred times, the floor's texture needs a hundredth.
        tiled = texture_density.needs(TEXT, [(mesh(8.0, 0.0), {'floor'})], CAMERA, 1920)['C:\\cache\\tiles.tx']
        self.assertLess(tiled, near)

    def test_an_animation_gets_the_most_of_its_frames(self):
        # The camera comes in from 2 km to 10 m over the shot: every frame is given the close frame's need, whichever
        # frame the scene was read at, so no texture changes size between frames.
        far = dict(CAMERA, matrix=CAMERA['matrix'][:12] + [0, 0, 2000, 1])
        placements = {'read': {'can': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]},
                      'frames': [{'camera': far['matrix'], 'can': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]},
                                 {'camera': CAMERA['matrix'], 'can': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}]}
        plane = dict(mesh(8.0, 0.0), source_item='can')
        close = texture_density.needs(TEXT, [(plane, {'can'})], CAMERA, 1920)
        from_far = texture_density.needs(TEXT, [(plane, {'can'})], far, 1920, placements)
        from_close = texture_density.needs(TEXT, [(plane, {'can'})], CAMERA, 1920, placements)
        self.assertEqual(from_far, close)
        self.assertEqual(from_close, close)
        self.assertGreater(close['C:\\cache\\label.tx'], texture_density.needs(TEXT, [(plane, {'can'})], far, 1920)['C:\\cache\\label.tx'])

    def test_an_animation_follows_its_meshes_items(self):
        # The plane's item moves from 2 km off to the camera over the shot: the near frame's need is kept.
        away = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, -2000, 1]
        plane = dict(mesh(8.0, -2000.0), source_item='can')
        placements = {'read': {'can': away},
                      'frames': [{'camera': CAMERA['matrix'], 'can': away},
                                 {'camera': CAMERA['matrix'], 'can': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}]}
        near = texture_density.needs(TEXT, [(mesh(8.0, 0.0), {'can'})], CAMERA, 1920)
        self.assertEqual(texture_density.needs(TEXT, [(plane, {'can'})], CAMERA, 1920, placements), near)

    def test_textures_no_mesh_wears_are_left_out(self):
        self.assertEqual(texture_density.needs(TEXT, [(mesh(8.0, 0.0), {'other'})], CAMERA, 1920), {})

    def test_the_user_data_for_xpu2(self):
        lines = texture_density.user_data({'C:\\cache\\b.tx': 512, 'C:\\cache\\a.tx': 2048})
        text = '\n'.join(lines)
        self.assertIn('UserData("/modo/xpu2/texture_density")', text)
        self.assertIn('["int_values"] = {2048, 512}', text)
        self.assertLess(text.index('a.tx'), text.index('b.tx'))
        self.assertEqual(texture_density.user_data({}), [])


if __name__ == '__main__':
    unittest.main()
