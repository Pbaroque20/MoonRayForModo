# python
"""Isolated GUI test: how Modo turns an Anisotropic Direction layer's value into the direction of a stretched highlight.

A UV sphere with a strongly anisotropic material is lit by Modo's default light in a black world. A solid grey image
on its UVs sets Anisotropic Direction to 0, 0.125, 0.25 and 0.5 in turn, and each is rendered by Modo
(modo_dir_<value>.exr). The scene is exported once (aniso.rdla) for tools/check_aniso_direction.py, which measures
which way each highlight points in Modo's renders and in MoonRay's at a range of tangent angles."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtGui

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/aniso-direction'
out.mkdir(parents=True, exist_ok=True)
for old in out.glob('*'):
    if old.is_file():
        old.unlink()
result = {'cases': []}
SIZE = 256
VALUES = (0.0, 0.125, 0.25, 0.5)

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
    lx.eval('select.item {%s} set' % camera.id)
    for axis, value in (('pos.X', 0), ('pos.Y', 0), ('pos.Z', 4), ('rot.X', 0), ('rot.Y', 0), ('rot.Z', 0)):
        lx.eval('transform.channel %s %s' % (axis, value))
    camera.channel('focalLen').set(0.05)
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    # Every setting given: Modo keeps a tool's settings from earlier runs.
    for attribute, value in (('cenX', 0), ('cenY', 0), ('cenZ', 0), ('sizeX', .5), ('sizeY', .5), ('sizeZ', .5), ('sides', 64), ('segments', 32)):
        lx.eval('tool.attr prim.sphere %s %s' % (attribute, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    material = next(iter(scene.items('advancedMaterial')))
    # The UV map the anisotropy runs along: without one Modo draws a round highlight.
    material.channel('uvMap').set('Texture')
    for name, value in (('brdfType', 'gtr'), ('diffAmt', 0.05), ('specAmt', 0.5), ('rough', 0.3), ('aniso', 0.9), ('specFres', 0.0)):
        material.channel(name).set(value)
    shader_root = material.parent
    if os.environ.get('MOONRAY_PROBE_GRID'):
        # Modo's anisotropy and roughness over a grid, each exported, for the translation to be fitted to.
        from moonray_modo import scene_export as exporter
        for aniso in (0.3, 0.6, 0.9):
            for rough in (0.2, 0.4):
                name = 'grid_a%g_r%g' % (aniso, rough)
                material.channel('aniso').set(aniso)
                material.channel('rough').set(rough)
                lx.eval('!render.animation {%s} openexr' % str(out / ('modo_' + name)))
                exporter.export({'path': out / (name + '.rdla'), 'format': 'rdla', 'outputs': False, 'collect': False, 'frames': False}, [])
                result['cases'].append({'grid': name})
        (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
        lx.eval('!app.quit')
    if os.environ.get('MOONRAY_PROBE_PLAIN'):
        # No direction layer: whether Modo stretches the highlight at all, under each model.
        for model in ('gtr', 'ashikhmin', 'blinn'):
            material.channel('brdfType').set(model)
            lx.eval('!render.animation {%s} openexr' % str(out / ('modo_plain_' + model)))
            result['cases'].append({'plain': model})
        (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
        lx.eval('!app.quit')
    layer = None
    for value in VALUES:
        entry = {'value': value}
        try:
            grey = int(round(255 * value))
            picture = QtGui.QImage(8, 8, QtGui.QImage.Format_RGB32)
            picture.fill(QtGui.QColor(grey, grey, grey))
            image = out / ('dir_%g.png' % value)
            picture.save(str(image))
            lx.eval('clip.addStill {%s}' % image)
            clip = scene.items('videoStill')[-1]
            if layer is None:
                lx.eval('item.create imageMap')
                layer = scene.selected[0]
                lx.eval('texture.parent {%s} %d item:{%s}' % (shader_root.id, len(shader_root.children()), layer.id))
                locator = next(i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
                locator.channel('projType').set('uv')
                locator.channel('uvMap').set('Texture')
                layer.channel('effect').set('anisoDir')
                # Read as stored: 8-bit grey is already the value wanted.
                layer.channel('colorspace').set('nuke-default:linear') if 'colorspace' in layer.channelNames else None
            lx.eval('select.item {%s} set' % layer.id)
            lx.eval('texture.setIMap {%s}' % clip.id)
            entry['effect'] = layer.channel('effect').get()
            lx.eval('!render.animation {%s} openexr' % str(out / ('modo_dir_%g' % value)))
        except Exception:
            entry['error'] = traceback.format_exc()
        result['cases'].append(entry)
        (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
    warnings = []
    scene_export.export({'path': out / 'aniso.rdla', 'format': 'rdla', 'outputs': False, 'collect': False, 'frames': False}, warnings)
    result['warnings'] = warnings
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
