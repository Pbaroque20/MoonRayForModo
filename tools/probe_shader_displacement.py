# python
"""Isolated GUI test: Shader Tree displacement and stencil layers, against Modo's own render.

A UV sphere is lit by Modo's default light in a black world. An image of vertical stripes is laid on it by its UVs,
first as a Displacement layer (white stripes raised by the material's Displacement Distance), then as a Stencil
layer (black stripes cut away). Each case is rendered by Modo (modo_<case>.exr) and exported as the plugin writes it
(<case>.rdla); tools/check_shader_displacement.py renders those with MoonRay and compares the outlines."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtGui

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/shader-displacement'
out.mkdir(parents=True, exist_ok=True)
for old in out.glob('*'):
    if old.is_file():
        old.unlink()
result = {'cases': []}
SIZE = 192
DISTANCE = 0.15

try:
    from moonray_modo import scene_export
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', SIZE), ('resY', SIZE), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    environment = next(iter(scene.items('environment')))
    envmat = next(i for i in environment.children() if i.type == 'envMaterial')
    envmat.channel('type').set('constant')
    for axis in 'RGB':
        envmat.channel('zenColor.' + axis).set(0.0)
    camera = scene.renderCamera
    camera.position.set((0, 0, 4.0))
    camera.rotation.set((0, 0, 0), degrees=True)
    camera.channel('focalLen').set(0.05)
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.attr prim.sphere sides 48')
    lx.eval('tool.attr prim.sphere segments 24')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    # Vertical stripes: eight white and eight black across the image, so across the sphere's U.
    picture = QtGui.QImage(256, 64, QtGui.QImage.Format_RGB32)
    for x in range(256):
        shade = 255 if (x // 16) % 2 == 0 else 0
        for y in range(64):
            picture.setPixel(x, y, QtGui.qRgb(shade, shade, shade))
    image = out / 'stripes.png'
    picture.save(str(image))
    material = next(iter(scene.items('advancedMaterial')))
    material.channel('displace').set(DISTANCE)
    lx.eval('clip.addStill {%s}' % image)
    clip = scene.items('videoStill')[-1]
    lx.eval('item.create imageMap')
    layer = scene.selected[0]
    shader_root = material.parent
    lx.eval('texture.parent {%s} %d item:{%s}' % (shader_root.id, len(shader_root.children()), layer.id))
    lx.eval('select.item {%s} set' % layer.id)
    lx.eval('texture.setIMap {%s}' % clip.id)
    locator = next(i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
    locator.channel('projType').set('uv')
    try:
        locator.channel('uvMap').set('Texture')
    except Exception:
        result['uv_map_error'] = traceback.format_exc()
    result['layer_parent'] = layer.parent.type
    for case in ('displace', 'stencil'):
        entry = {'case': case}
        try:
            layer.channel('effect').set(case)
            entry['effect'] = layer.channel('effect').get()
            lx.eval('!render.animation {%s} openexr' % str(out / ('modo_' + case)))
            warnings = []
            scene_export.export({'path': out / (case + '.rdla'), 'format': 'rdla', 'outputs': False, 'collect': False, 'frames': False}, warnings)
            entry['warnings'] = warnings
        except Exception:
            entry['error'] = traceback.format_exc()
        result['cases'].append(entry)
        (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
