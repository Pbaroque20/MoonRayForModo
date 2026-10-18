# python
"""Isolated GUI test: which way an HDRI environment turns, in Modo's own render and as the plugin sends it to MoonRay.

An image layer under the environment shows the HDRI given in MOONRAY_PROBE_HDRI (spherical Texture Locator), seen by a
wide camera in four directions a quarter turn apart (the whole horizon), with nothing else in view (a small cube sits
behind the camera: MoonRay draws no environment in a scene with no geometry). Modo renders the HDRI turned (Rotation Y
of its locator) by each eighth of a turn; the plugin's scene for MoonRay is written plain at 0 and 90 degrees, and
layered (at 90% opacity over the environment's black material, which the plugin bakes with it) at 90.
tools/check_hdri_turn.py renders the scenes and says which of Modo's turns each is nearest."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/hdri-turn'
out.mkdir(parents=True, exist_ok=True)
result = {'exports': {}}
SIZE = (192, 96)
VIEWS = (0, 90, 180, 270)
MODO_TURNS = (0, 45, 90, 135, 180, 225, 270, 315)
EXPORTS = (('plain_0', 0, 1.0), ('plain_90', 90, 1.0), ('layered_90', 90, .9))


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


try:
    for old in out.glob('*'):
        if old.is_file():
            old.unlink()
    from moonray_modo import host, rdla
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', SIZE[0]), ('resY', SIZE[1]), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    next(iter(scene.items('sunLight'))).channel('render').set('off')
    camera = scene.renderCamera
    camera.position.set((0, 0, 0))
    camera.channel('focalLen').set(0.012)
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    for attribute, value in (('sizeX', .1), ('sizeY', .1), ('sizeZ', .1), ('cenZ', 5.0)):
        lx.eval('tool.attr prim.cube %s %s' % (attribute, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    environment = next(iter(scene.items('environment')))
    lx.eval('clip.addStill {%s}' % os.environ['MOONRAY_PROBE_HDRI'])
    clip = scene.items('videoStill')[-1]
    lx.eval('item.create imageMap')
    layer = scene.selected[0]
    # On top of the environment's own material, as an HDRI is in a scene.
    lx.eval('texture.parent {%s} %d item:{%s}' % (environment.id, len(environment.children()), layer.id))
    lx.eval('select.item {%s} set' % layer.id)
    lx.eval('texture.setIMap {%s}' % clip.id)
    layer.channel('effect').set('envColor')
    locator = next(i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
    locator.channel('projType').set('spherical')
    material = next((i for i in environment.children() if i.type == 'envMaterial'), None)
    if material is not None:
        material.channel('type').set('constant')
        for axis in 'RGB':
            material.channel('zenColor.' + axis).set(0.0)

    def turn(degrees, opacity):
        lx.eval('select.item {%s} set' % locator.id)
        lx.eval('transform.channel rot.Y %f' % degrees)
        layer.channel('opacity').set(opacity)
        # Plain: the image alone. Layered: over the environment's own (black) material.
        if material is not None:
            material.channel('enable').set(opacity < 1)

    for degrees in MODO_TURNS:
        turn(degrees, 1.0)
        for view in VIEWS:
            camera.rotation.set((0, view, 0), degrees=True)
            lx.eval('!render.animation {%s} openexr' % str(out / ('modo_%d_%d' % (degrees, view))))
    for name, degrees, opacity in EXPORTS:
        entry = {}
        try:
            turn(degrees, opacity)
            for view in VIEWS:
                camera.rotation.set((0, view, 0), degrees=True)
                snapshot = host.snapshot()
                (out / ('%s_%d.rdla' % (name, view))).write_text(
                    rdla.scene_text(snapshot, SIZE[0], SIZE[1], 3, 0.0, str(out / ('moonray_%s_%d.exr' % (name, view)))), encoding='utf-8')
                # The scene as read, for MoonLightIPR to draw too.
                kept = {k: v for k, v in snapshot.items() if not k.startswith('_')}
                (out / ('%s_%d.json' % (name, view))).write_text(json.dumps(kept, default=str), encoding='utf-8')
            environments = snapshot.get('environments') or []
            entry['environment_kind'] = environments[0]['kind'] if environments else None
            entry['warnings'] = [w for w in snapshot.get('warnings', []) if 'renderOutput' not in w][:6]
        except Exception:
            entry['error'] = traceback.format_exc()
        result['exports'][name] = entry
        save()
    camera.rotation.set((0, 0, 0), degrees=True)
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
