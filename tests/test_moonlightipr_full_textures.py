"""MoonLightIPR's Render and Render Animation have each image at its full size; realtime's are fitted to 1024. No Modo."""
import pathlib
import sys
import unittest

KIT = pathlib.Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'
sys.path.insert(0, str(KIT))

from moonray_modo import moonlightipr_materials as materials  # noqa: E402


class FullTexturesForRender(unittest.TestCase):
    def test_realtime_keeps_the_limit(self):
        self.assertEqual(materials.Compiler().side, materials.MAX_TEXTURE_SIDE)
        self.assertEqual(materials.MAX_TEXTURE_SIDE, 1024)

    def test_render_and_animation_ask_for_full_size(self):
        render = (KIT / 'moonray_modo/render.py').read_text(encoding='utf-8')
        self.assertIn('_flat_out=True,_full_textures=True', render)
        playblast = (KIT / 'moonray_modo/playblast.py').read_text(encoding='utf-8')
        self.assertIn("snapshot['_full_textures'] = True", playblast)

    def test_the_scene_chooses_the_size(self):
        scene = (KIT / 'moonray_modo/moonlightipr_scene.py').read_text(encoding='utf-8')
        self.assertIn("Compiler(runtime, 0 if scene.get('_full_textures') else MAX_TEXTURE_SIDE)", scene)
        self.assertIn("environment_image(baked, runtime, bool(scene.get('_full_textures')))", scene)

    def test_full_size_is_cached_apart(self):
        source = (KIT / 'moonray_modo/moonlightipr_materials.py').read_text(encoding='utf-8')
        # 1024 keeps the cache key it had; a Render's full size has its own.
        self.assertIn("stat.st_mtime_ns, self.side or 'full', 'moonlightipr-v4'", source)
        self.assertIn("elif self.side and max(width, height) > self.side:", source)


if __name__ == '__main__':
    unittest.main()
