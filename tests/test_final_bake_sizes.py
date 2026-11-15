"""MoonShine graphs baked for MoonLightIPR at a final render's sizes (graph_bake.final, set by moonlightipr_scene's pack
for a Render, whose images are at their full size): over an image, that image's own size within FINAL_TILE_LIMIT; a
map of its own at FINAL_RESOLUTION; one laid out in the object's space at FINAL_SOLID_RESOLUTION. Realtime keeps its
sizes."""
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import graph_bake, moonlightipr_scene  # noqa: E402

GRAPH = {'nodes': {'img': {'type': 'image', 'parameters': {'file': 'C:/big.png'}, 'inputs': {}}}}


class FinalBakeSizes(unittest.TestCase):
    def test_outside_a_final_render_the_usual_sizes(self):
        self.assertIsNone(graph_bake.final_size(GRAPH, 'img', None))

    def test_a_final_render_bakes_at_the_image_s_own_size(self):
        with graph_bake.final(), mock.patch.object(graph_bake, 'image_side', return_value=4096):
            self.assertEqual(graph_bake.final_size(GRAPH, 'img', None), 4096)
        with graph_bake.final(), mock.patch.object(graph_bake, 'image_side', return_value=16384):
            self.assertEqual(graph_bake.final_size(GRAPH, 'img', None), graph_bake.FINAL_TILE_LIMIT)
        with graph_bake.final(), mock.patch.object(graph_bake, 'image_side', return_value=None):
            self.assertEqual(graph_bake.final_size(GRAPH, 'img', None), graph_bake.TILE_RESOLUTION)
        with graph_bake.final():
            self.assertEqual(graph_bake.final_size(GRAPH, None, None), graph_bake.FINAL_RESOLUTION)
            self.assertEqual(graph_bake.final_size(GRAPH, None, {'box': 1}), graph_bake.FINAL_SOLID_RESOLUTION)
        with graph_bake.final(False):
            self.assertIsNone(graph_bake.final_size(GRAPH, None, None))

    def test_a_render_s_pack_is_final_and_realtime_s_is_not(self):
        seen = []
        with mock.patch.object(moonlightipr_scene, '_pack', lambda *a: seen.append(graph_bake._FINAL.get()) or (b'', [], [])):
            moonlightipr_scene.pack({'materials': {}, 'meshes': [], '_full_textures': True}, 64, 36)
            moonlightipr_scene.pack({'materials': {}, 'meshes': []}, 64, 36)
        self.assertEqual(seen, [True, False])


if __name__ == '__main__':
    unittest.main()
