# python
"""Isolated GUI test: the kinds of material the plugin adds to the Shader Tree reach the render. A MaterialX material by import and by
Add Layer then Load, and a MoonRay material added as a layer; each is looked for in what the plugin reads from the scene."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/material-types'
out.mkdir(parents=True, exist_ok=True)
result = {}
SOURCE = os.environ.get('PROBE_MTLX', '')


def ball(name, x):
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    for key, value in (('cenX', x), ('cenY', 0.5), ('cenZ', 0), ('sizeX', 0.4), ('sizeY', 0.4), ('sizeZ', 0.4)):
        lx.eval('tool.attr prim.sphere %s %s' % (key, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    mesh = modo.Scene().selected[0]
    mesh.name = name
    return mesh


def tagged(mesh, tag):
    with mesh.geometry as g:
        for index in range(len(g.polygons)):
            g.polygons[index].materialTag = tag


def layer(kind, tag, name):
    """A material of one of the plugin's kinds under a mask for a tag, as Add Layer leaves it."""
    scene = modo.Scene()
    mask = scene.addItem('mask', name=name + ' mask')
    from moonray_modo import materials
    mask.setParent(scene.renderItem, materials.above_base(scene, mask))
    mask.channel('ptyp').set('Material')
    mask.channel('ptag').set(tag)
    item = scene.addItem(kind, name=name)
    item.setParent(mask, 0)
    return item


try:
    from moonray_modo import host, properties
    scene = modo.Scene()
    # 1. Imported from the menu onto a mesh.
    first = ball('Imported', -1.0)
    scene.select(first)
    lx.eval('moonray.material.importMaterialX {%s}' % SOURCE)
    made = [item for item in scene.items() if item.type == properties.MATERIALX_TYPE]
    result['imported'] = [[item.name, item.type] for item in made]
    # 2. Added as a layer, empty, then given its file.
    second = ball('Layered', 0.0)
    tagged(second, 'layered')
    empty = layer(properties.MATERIALX_TYPE, 'layered', 'MaterialX Material')
    settings = properties.read(empty)
    result['empty'] = {key: settings.get(key) for key in ('shader', 'native_shader', 'moonshine_override')}
    scene.select(empty)
    result['load_enabled'] = bool(lx.eval('query commandservice command.enable ? moonray.material.loadMaterialX')) if False else None
    lx.eval('moonray.material.loadMaterialX {%s}' % SOURCE)
    loaded = properties.read(empty)
    result['loaded'] = [empty.name, len((loaded.get('node_graph') or {}).get('nodes', {})), len((loaded.get('node_graph') or {}).get('controls', []))]
    # 3. A MoonRay material added as a layer.
    third = ball('Metal', 1.0)
    tagged(third, 'metal')
    metal = layer(properties.LAYER_PREFIX + 'DwaMetalMaterial', 'metal', 'DwaMetalMaterial')
    snapshot = host.snapshot()
    result['warnings'] = [w for w in snapshot.get('warnings', []) if 'renderOutput' not in w]
    found = {}
    for tag, material in snapshot['materials'].items():
        found[tag or '(default)'] = [material.get('name'), material.get('native_shader'), len((material.get('node_graph') or {}).get('nodes', {})),
                                     bool(material.get('node_override'))]
    result['materials'] = found
    result['mesh_tags'] = {mesh['name']: mesh.get('material') for mesh in snapshot['meshes']}
    scene.select(empty)
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def step2():
    try:
        for index, window in enumerate(w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible() and w.width() > 300):
            window.grab().save(str(out / ('form-%d.png' % index)))
    except Exception:
        result['step2_error'] = traceback.format_exc()
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(5000, step2)
