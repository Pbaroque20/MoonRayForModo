"""Render a quad captured from Modo with its image applied three ways, in MoonRay and MoonLight.

tools/probe_graph_image_capture.py makes the capture: a quad facing the camera whose material
reads an image wired in its graph. The image has red rising with u, blue with v, and a bright
green corner at u, v = 0, 0, so a turn, flip or shift of the mapping shows at a glance.

  wired          as captured: the image node in the material's graph
  layer_named    the same image as a Shader Tree layer on the UV set the plugin bakes for it
  layer_primary  the same image as a Shader Tree layer on the mesh's own UVs

Writes one PNG per variant under test-results/graph-image, MoonRay on the left and MoonLight on
the right, and prints how far the pictures are from one another, in mean tile luminance.

Usage: python tools/check_graph_image.py <runtime folder>
"""
import copy
import json
import os
import pathlib
import struct
import sys
import zlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import compare_moonlight as compare  # noqa: E402
from moonray_modo import native  # noqa: E402

root = pathlib.Path(__file__).resolve().parents[1]
folder = root / 'test-results/graph-image'
WIDTH, HEIGHT = compare.WIDTH, compare.HEIGHT


def write_png(path, left, right):
    encode = lambda v: round(255 * (12.92 * v if v <= .0031308 else 1.055 * v ** (1 / 2.4) - .055))
    rows = []
    for y in reversed(range(HEIGHT)):
        rows.append(b'\x00' + bytes(encode(min(1.0, max(0.0, v))) for image in (left, right) for v in image[y * WIDTH * 3:(y + 1) * WIDTH * 3]))
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', WIDTH * 2, HEIGHT, 8, 2, 0, 0, 0))
                     + chunk(b'IDAT', zlib.compress(b''.join(rows))) + chunk(b'IEND', b''))


def variants(snapshot):
    tag = next(key for key, value in snapshot['materials'].items() if key and value.get('node_graph'))
    material = snapshot['materials'][tag]
    graph = material['node_graph']
    image = next(node for node in graph['nodes'].values() if node['type'] == 'image')
    key = next(iter(snapshot['meshes'][0]['uv_sets']))
    def layered(named):
        scene = copy.deepcopy(snapshot)
        plain = {k: v for k, v in material.items() if k != 'node_graph'}
        layer = {'identity': 'layer', 'kind': 'imageMap', 'effect': 'diffCol', 'path': image['parameters']['file'], 'srgb': True,
                 'projection': 'uv', 'uv_map': '', 'scale': [1, 1], 'opacity': 1.0, 'blend': 'normal'}
        if named:
            layer['coordinate_key'] = key
        scene['materials'][tag] = {'material_stack': [dict(plain, node_override=False, base_layer_id='base', layers=[layer])]}
        return scene
    return {'wired': copy.deepcopy(snapshot), 'layer_named': layered(True), 'layer_primary': layered(False)}


def main():
    runtime = native.find_runtime(sys.argv[1])
    os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
    snapshot = json.loads((folder / 'snapshot.json').read_text())
    session = compare.fixture.Session(folder)
    session.runtime = runtime
    first = None
    try:
        for name, scene in variants(snapshot).items():
            scene['width'], scene['height'] = WIDTH, HEIGHT
            reference = compare.moonray(scene, runtime, folder, name)
            preview, warnings = compare.moonlight(scene, session, name)
            write_png(folder / (name + '.png'), reference, preview)
            # How far apart the two engines are, and how far each variant is from the first.
            worst = max(abs(x - y) for x, y in zip(compare.blocks(reference), compare.blocks(preview)))
            first = first or (name, compare.blocks(reference), compare.blocks(preview))
            print('%-14s largest tile difference MoonRay to MoonLight %.3f; MoonRay to %s %.3f; MoonLight to %s %.3f' % (
                name, worst, first[0], max(abs(x - y) for x, y in zip(compare.blocks(reference), first[1])),
                first[0], max(abs(x - y) for x, y in zip(compare.blocks(preview), first[2]))))
            for warning in warnings:
                print('  note:', warning)
        session.process.stdin.write(b'quit' + bytes([10]))
        session.process.stdin.flush()
        session.process.wait(timeout=10)
    finally:
        if session.process.poll() is None:
            session.process.kill()


if __name__ == '__main__':
    main()
