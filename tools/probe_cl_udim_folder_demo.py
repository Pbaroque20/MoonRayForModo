# python
"""Command line: a UDIM set as an FBX import leaves it in Modo, read by the kit and written for MoonRay. A cube whose six
faces each lie in their own UDIM tile (1001 to 1006), an Image Folder of six images each carrying its tile's number,
and an image layer laid on through the folder with Use UDIM on and its repeat modes on Reset (textures.folder_tiles,
layers). PROBE_TILES the folder of the images (name.<number>.png), PROBE_SIZE pixels wide (480, at 16:10),
PROBE_SAMPLES (16). Writes test-results/udim-demo/report.json (the layer as the kit reads it, the scene's notices) and
scene.rdla for rendering outside Modo (PROBE_OUT for another folder)."""
import json
import math
import os
import pathlib
import traceback

import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\udim-demo'))
out.mkdir(parents=True, exist_ok=True)
tiles = pathlib.Path(os.environ.get('PROBE_TILES', str(out / 'tiles')))
report = {}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


# Each face: its normal, the direction its image's right runs, and its up (right x up = normal: outward).
FACES = [((0, 0, 1), (1, 0, 0), (0, 1, 0)), ((1, 0, 0), (0, 0, -1), (0, 1, 0)), ((0, 1, 0), (1, 0, 0), (0, 0, -1)),
         ((0, 0, -1), (-1, 0, 0), (0, 1, 0)), ((-1, 0, 0), (0, 0, 1), (0, 1, 0)), ((0, -1, 0), (1, 0, 0), (0, 0, 1))]


def step(name):
    report.setdefault('steps', []).append(name)
    save()


try:
    scene = modo.Scene()
    step('start')
    lx.eval('layer.new')
    step('layer')
    mesh = scene.selected[-1]
    geometry = mesh.geometry
    uv = geometry.vmaps.addMap(lx.symbol.i_VMAP_TEXTUREUV, 'Texture')
    step('uv map')
    for tile, (normal, right, up) in enumerate(FACES):
        corners = []
        for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            corners.append(geometry.vertices.new(tuple(.5 * n + .5 * a * r + .5 * b * u for n, r, u in zip(normal, right, up))))
        polygon = geometry.polygons.new(corners)
        for corner, (a, b) in zip(corners, ((0, 0), (1, 0), (1, 1), (0, 1))):
            polygon.setUV((tile + a, b), corner, uv)
    step('polygons')
    geometry.setMeshEdits()
    step('mesh edits')
    report['mesh'] = {'points': geometry.numVertices, 'polygons': geometry.numPolygons}

    # The images, each with its tile's number, in an Image Folder.
    folder = scene.addItem('imageFolder', name='demo')
    step('folder')
    numbers = []
    for path in sorted(tiles.glob('demo.*.png')):
        number = int(path.stem.split('.')[-1])
        lx.eval('clip.addStill {%s}' % path)
        clip = next(c for c in scene.items('videoStill') if pathlib.Path(c.channel('filename').get()).name == path.name)
        clip.channel('udim').set(number)
        clip.setParent(folder)
        numbers.append(number)
    report['tiles'] = numbers
    step('clips')

    # An image layer just above the base material, laid on through the folder by its texture locator, as an FBX import
    # links them (shadeLoc: the layer to its locator and to the folder). Made as items: shader.create crashes the
    # command-line Modo.
    shader = next(i for i in scene.renderItem.children() if i.type == 'defaultShader')
    layer = scene.addItem('imageMap', name='demo (Image)')
    # Children run bottom row first; setParent puts it one after the index given: so between the Base Material and the
    # Base Shader, the row just below the shader.
    layer.setParent(scene.renderItem, max(0, shader.parentIndex - 1))
    layer.channel('effect').set('diffColor')
    report['tree'] = [(i.type, i.name) for i in scene.renderItem.children()]
    graph = lx.object.ItemGraph(lx.object.Scene(layer._item.Context()).GraphLookup('shadeLoc'))
    graph.AddLink(layer._item, folder._item)
    # Its texture locator, made with it.
    locator = next(i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
    step('image layer')
    for name, value in (('projType', 'uv'), ('uvMap', 'Texture'), ('useUDIM', 1), ('tileU', 'reset'), ('tileV', 'reset')):
        locator.channel(name).set(value)
    report['layer_links'] = [(i.type, i.name) for i in layer.itemGraph('shadeLoc').forward()]

    # The camera at three quarters, looking at the cube's middle.
    camera = scene.renderCamera
    eye = (2.3, 1.75, 2.7)
    camera.position.set(eye)
    camera.rotation.set((-math.atan2(eye[1], math.hypot(eye[0], eye[2])), math.atan2(eye[0], eye[2]), 0.0))
    save()

    from moonray_modo import host, rdla
    snapshot = host.snapshot(evaluated_geometry=False)
    found = []
    for tag, material in (snapshot.get('materials') or {}).items():
        for row in material.get('material_stack') or [material]:
            found += [{k: l.get(k) for k in ('effect', 'kind', 'path', 'tile_u', 'tile_v', 'uv_map')} for l in row.get('layers') or []]
    report['layers'] = found
    report['warnings'] = snapshot.get('warnings')
    width = int(os.environ.get('PROBE_SIZE', 480))
    text = rdla.scene_text(snapshot, width, width * 10 // 16, int(os.environ.get('PROBE_SAMPLES', 16)), 0.15, str(out / 'out.exr'))
    (out / 'scene.rdla').write_text(text, encoding='utf-8')
    report['rdla_bytes'] = len(text)
except Exception:
    report['error'] = traceback.format_exc()
save()
