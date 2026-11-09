# python
"""GUI: Scene Proxies and imported references as the kit reads and MoonRay renders them, beside Modo's renders.

Needs test-results/references/src.lxo, proxy.lxo and referencing.lxo (tools/probe_references.py, tools/probe_proxy.py).
proxy.lxo gets a second proxy of the same file at x=-2.5 (proxy2.lxo). For each scene: the meshes the kit's snapshot
gives (with each one's material colour), Modo's render (<name>-modo) and the MoonRay preview's (<name>-moonray.png).
Writes test-results/references/render.json."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore

out = pathlib.Path(os.environ.get('PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\references')
result = {}
SCENES = __import__('os').environ.get('PROBE_SCENES', 'proxy2,referencing').split(',')


def save():
    (out / 'render.json').write_text(json.dumps(result, indent=1, default=str))


def place_camera(scene):
    # A referenced scene's render item or camera may be the referenced file's, which Modo will not let be set: noted.
    refused = result.setdefault('refused', [])
    # Every render item: a referencing scene has its own and the referenced file's, and Modo renders the frame range
    # of one the scene's renderItem need not be (it rendered a whole animation once).
    for render_item in scene.items('polyRender'):
        for name, value in (('resX', 480), ('resY', 270), ('first', 1), ('last', 1)):
            try:
                render_item.channel(name).set(value)
            except RuntimeError as error:
                refused.append('%s %s: %s' % (render_item.id, name, error))
    result.setdefault('render_items', {})[scene.filename] = [item.id for item in scene.items('polyRender')]
    # The scene's own frame range as well (the Time range Modo's render follows).
    try:
        lx.eval('time.range scene 0.0 0.0')
    except RuntimeError as error:
        refused.append('time.range: %s' % error)
    try:
        lx.eval('select.item {%s} set' % scene.renderCamera.id)
        for channel, value in (('pos.X', 0), ('pos.Y', 2), ('pos.Z', 7), ('rot.X', -12), ('rot.Y', 0)):
            lx.eval('transform.channel %s %s' % (channel, value))
    except RuntimeError as error:
        refused.append('camera: %s' % error)
    lx.eval('select.drop item')


def kit_read():
    from moonray_modo import host
    snap = host.snapshot()
    materials = snap.get('materials', {})
    return {'meshes': [(m.get('identity'), m.get('material'), [round(c, 3) for c in (materials.get(m.get('material')) or {}).get('color', [])],
                        len(m.get('instances') or []) or 1, [round(v, 3) for v in (m.get('matrix') or [])[12:15]])
                       for m in snap.get('meshes', [])],
            'warnings': [w for w in snap.get('warnings', []) if 'roxy' in w or 'material' in w.lower()][:10]}


def prepare(name):
    if name == 'proxy2':
        lx.eval('!scene.open {%s} normal' % (out / 'proxy.lxo'))
        scene = modo.Scene()
        lx.eval('item.create proxy')
        second = [i for i in scene.iterItems() if i.type == 'proxy'][-1]
        lx.eval('!proxy.sceneFile item:{%s} filename:{%s}' % (second.id, out / 'src.lxo'))
        lx.eval('!proxy.renderItem item:{%s} name:{RefCube}' % second.id)
        lx.eval('select.item {%s} set' % second.id)
        lx.eval('transform.channel pos.X -4.5')
        lx.eval('select.drop item')
    else:
        lx.eval('!scene.open {%s} normal' % (out / (name + '.lxo')))
    scene = modo.Scene()
    place_camera(scene)
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / (name + '-test.lxo')))
    # Modo's render, where there is none yet: a referencing scene's render item is the referenced file's, whose frame
    # range cannot be set here, and Modo rendered all 120 of its frames.
    if not (out / (name + '-modo.Final Color Output.0001.png')).is_file():
        lx.eval('!render.animation {%s} PNG' % (out / (name + '-modo')))
    result[name] = {'kit': kit_read()}
    save()


def panel_widget():
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def render(index):
    if index >= len(SCENES):
        return finish()
    name = SCENES[index]
    try:
        if index:
            prepare(name)
        p = panel_widget()
        if index == 0:
            p.preferences.set('preview_fraction', 1)
            p._store(execution_mode='xpu')
            p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonray'))
        p.render_once()
        began = time.monotonic()

        def wait():
            try:
                q = panel_widget()
                if (getattr(q, '_rendering', False) and time.monotonic() - began < 240) or time.monotonic() - began < 6:
                    QtCore.QTimer.singleShot(1500, wait); return

                def grab():
                    q.preview.image.save(str(out / (name + '-moonray.png')))
                    result[name]['preview'] = [q.status.text(), q.image_info.text()]
                    save(); render(index + 1)
                QtCore.QTimer.singleShot(3000, grab)
            except Exception:
                result[name + '_wait_error'] = traceback.format_exc(); save(); render(index + 1)
        QtCore.QTimer.singleShot(2000, wait)
    except Exception:
        result[name + '_error'] = traceback.format_exc(); save(); render(index + 1)


def finish():
    try:
        panel_widget().stop()
    except Exception:
        result['finish_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


try:
    prepare(SCENES[0])
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: render(0))
