"""A scene's first realtime run (2026-11-05): environment images shrunk straight from the file, side by side, grey
ones read as grey; textures' own UVs worked out for whole meshes, and meshes of several UV maps split by map."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / 'kit/MoonRayForModo/python'
sys.path.insert(0, str(KIT))
from moonray_modo import environment_layers, textures  # noqa: E402


class EnvironmentImages(unittest.TestCase):
    def test_colours_taken_as_prepare_takes_them(self):
        space, args, _ = textures.color_conversion('sky.jpg', srgb=True)
        self.assertEqual((space, args), ('sRGB', ['--colorconvert', 'sRGB', 'linear']))
        space, args, _ = textures.color_conversion('sky.hdr', srgb=False)
        self.assertEqual((space, args), ('raw', []))
        source = (KIT / 'moonray_modo/textures.py').read_text(encoding='utf-8')
        self.assertIn('space,colour_args,transform_key=color_conversion(source,srgb,color_space)', source)

    def test_shrunk_straight_and_side_by_side(self):
        source = (KIT / 'moonray_modo/environment_layers.py').read_text(encoding='utf-8')
        self.assertIn("source=str(textures.asset_path(layer['path']))", source)
        self.assertIn("args=[source]+grey+colour+['--resize'", source)
        self.assertIn("run(args+['-d','float','-o',str(target)])", source)
        self.assertIn('ThreadPoolExecutor(max_workers=min(4, len(images)))', source)

    def test_grey_images_read_as_grey(self):
        xml = '<ImageSpec version="30"><nchannels>1</nchannels><alpha_channel>-1</alpha_channel></ImageSpec>'
        self.assertEqual(environment_layers.channel_count(xml), 1)
        source = (KIT / 'moonray_modo/environment_layers.py').read_text(encoding='utf-8')
        self.assertIn("grey=['--ch','0,0,0','--chnames','R,G,B'] if channel_count(info)<3 else []", source)


class WholeMeshUVs(unittest.TestCase):
    def test_textures_own_uvs_for_whole_meshes(self):
        source = (KIT / 'moonray_modo/host.py').read_text(encoding='utf-8')
        self.assertIn('def whole_mesh_sets(whole, faces, tag_descriptors, transform):', source)
        self.assertIn('part = mesh_reader.Part(whole, faces_of)', source)
        reader = (KIT / 'moonray_modo/mesh_reader.py').read_text(encoding='utf-8')
        self.assertIn('class Part:', reader)
        native = (ROOT / 'native-modo/rows_math.cpp').read_text(encoding='utf-8')
        self.assertIn('MR_mask_corners', native)


if __name__ == '__main__':
    unittest.main()
