# python
"""Command-line test: the scene a graph editor node preview renders (graph_bake.written), written inside Modo, for a
graph like an artist's: an image through an HSV colour correction. Writes test-results/cl-export/prep/node_preview.rdla
and node_preview.json; tools render and compare it outside Modo."""
import json
import pathlib
import traceback
import lx

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/cl-export/prep'
image = str(root / 'downloads/moonray-example-scenes/scenes/bedroom/textures/wallpaper-1_moonray.tx')
graph = {'version': 1, 'nodes': {'i': {'type': 'image', 'parameters': {'file': image, 'uv_map': 'Texture'}},
                                 'n': {'type': 'ColorCorrectHsvMap', 'parameters': {}, 'inputs': {'input': 'i'}}}}
result = {}
try:
    lx.eval('scene.new')
    from moonray_modo import graph_bake, rdla
    made = graph_bake.scene(graph, 'n', None)
    made['width'] = made['height'] = 96
    text = rdla.scene_text(made, 96, 96, 2, 0.0, str(out / 'node_preview.exr'))
    (out / 'node_preview.rdla').write_text(text, encoding='utf-8')
    result['bytes'] = len(text)
except Exception:
    result['error'] = traceback.format_exc()
(out / 'node_preview.json').write_text(json.dumps(result, indent=1))
