# python
"""GUI: seas on Modo's own meshes in the viewport (ocean_meshes.py). A new scene: a 40 m plane of 4 x 4 quads at 2 m, its
UVs Modo's planar projection, wearing a MoonShine material whose graph displaces it by an Ocean node (four tiles
across), written as the graph editor writes it (properties.write, which gives the plane the kit's package); and an
Ocean Plane at -4 m whose material tag names that material. The render camera above, looking down at the plane. Then,
a few seconds apart: the viewport as it opens, looking through the render camera, the timeline at 2 s, and the scene
saved and opened again (a second plane wearing the material by its tag alone given the package as it opens). At each: the main window's
picture (taken off the screen: run with --show), whether the plane carries the package, each drawing's points
(ocean_meshes.LAST, ocean_viewport.LAST) and any fault (ocean_meshes.FAULTS, entities.DRAW_FAULTS). Writes
test-results/ocean-meshes-gui/report.json and the pictures (PROBE_OUT for another folder). Run with
tools/launch_gui_probe.py probe_gui_ocean_meshes.py --show --kit-source <a kit with this adapter and modo_ocean.dll>."""
import json
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore, QtGui, QtWidgets

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\ocean-meshes-gui'))
out.mkdir(parents=True, exist_ok=True)
report = {'stages': [], 'errors': []}
state = {'t0': time.monotonic()}
SIZE, SEGMENTS, HEIGHT = 40.0, 4, 2.0


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def later(fn, wait):
    def run():
        try:
            fn()
        except Exception:
            report['errors'].append(traceback.format_exc())
            finish()
    QtCore.QTimer.singleShot(wait, run)


def main_window():
    shown = [w for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, QtWidgets.QMainWindow) and w.isVisible()]
    return max(shown, key=lambda w: w.width() * w.height(), default=None)


def plane(name='Sea Plane'):
    import modo
    return next((m for m in modo.Scene().items('mesh') if m.name == name), None)


def flat_mesh(scene, name, x):
    """A 40 m plane of 4 x 4 quads at HEIGHT, centred at x, with Modo's planar UVs."""
    import modo
    made = scene.addMesh(name)
    with made.geometry as geo:
        rows = []
        for j in range(SEGMENTS + 1):
            z = SIZE / 2 - SIZE * j / SEGMENTS
            rows.append([geo.vertices.new((x - SIZE / 2 + SIZE * i / SEGMENTS, HEIGHT, z)) for i in range(SEGMENTS + 1)])
        for j in range(SEGMENTS):
            for i in range(SEGMENTS):
                # Wound so that its normal points up (as probe_cl_ocean_scene's sea).
                geo.polygons.new([rows[j][i], rows[j][i + 1], rows[j + 1][i + 1], rows[j + 1][i]])
    lx.eval('select.item {%s} set' % made.id)
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('vertMap.new Texture txuv')
    lx.eval('tool.set uv.create on')
    lx.eval('tool.reset')
    lx.eval('tool.attr uv.create proj planar')
    lx.eval('tool.attr uv.create axis 1')
    lx.eval('tool.doApply')
    lx.eval('tool.set uv.create off')
    lx.eval('select.drop polygon')
    lx.eval('select.type item')
    return made


def where():
    """Each drawn surface's points worked out again from its last drawing (its eye and settings), and where they lie:
    their count and the box around them; with each plane's own box."""
    import modo
    from moonray_modo import ocean_viewport
    found = {}
    for name, last in ocean_viewport.LAST.items():
        if 'sea' not in last:
            continue
        points = ocean_viewport.surface_points(last['sea'], name, last['repeat'], last['factor'], last['eye'], last['spacing'],
                                               last['distance']) or []
        box = [[round(min(p[k] for p in points), 2), round(max(p[k] for p in points), 2)] for k in range(3)] if points else None
        found[name] = {'count': len(points), 'box': box, 'eye': [round(v, 2) for v in last['eye']]}
    for mesh in modo.Scene().items('mesh'):
        try:
            places = [v.position for v in mesh.geometry.vertices]
            found[mesh.name + ' ' + mesh.id] = [[round(min(p[k] for p in places), 2), round(max(p[k] for p in places), 2)] for k in range(3)]
        except Exception:
            pass
    return found


def stage(name):
    from moonray_modo import entities, ocean_meshes, ocean_viewport
    window = main_window()
    if window is not None:
        QtGui.QGuiApplication.primaryScreen().grabWindow(window.winId()).save(str(out / (name.replace(' ', '-') + '.png')))
    seas, every = ocean_meshes.scene_seas(fresh=True)
    report['stages'].append({'stage': name, 'seconds': round(time.monotonic() - state['t0'], 1),
                             'scene_time': lx.service.Selection().GetTime(),
                             'package': {n: bool(plane(n) is not None and plane(n).PackageTest(ocean_meshes.PACKAGE))
                                         for n in ('Sea Plane', 'Second Plane')},
                             'calls': dict(ocean_meshes.CALLS),
                             'where': where(),
                             'seas': {tag: {'material': sea['material'], 'factor': sea['factor']} for tag, sea in seas.items()},
                             'mesh_drawn': {k: {key: v for key, v in d.items() if key != 'facts'} for k, d in ocean_meshes.LAST.items()},
                             'mesh_facts': {k: d.get('facts') for k, d in ocean_meshes.LAST.items()},
                             'drawn': {k: dict(v) for k, v in ocean_viewport.LAST.items()},
                             'faults': dict(ocean_meshes.FAULTS), 'entity_faults': dict(entities.DRAW_FAULTS)})
    ocean_viewport.DRAWS.clear()
    save()


def opened():
    stage('opened')
    try:
        lx.eval('view3d.projection cam')
    except Exception:
        report['errors'].append(traceback.format_exc()[-600:])
    later(through_camera, 4000)


def through_camera():
    stage('through the camera')
    lx.eval('select.time 2.0')
    later(moved_on, 4000)


def moved_on():
    stage('at 2 s')
    try:
        lx.eval('view3d.projection psp')
    except Exception:
        report['errors'].append(traceback.format_exc()[-600:])
    later(in_perspective, 4000)


def in_perspective():
    stage('perspective')
    path = out / 'ocean_meshes.lxo'
    lx.eval('!scene.saveAs {%s} $LXOB false' % path)
    lx.eval('!scene.close')
    lx.eval('scene.open {%s}' % path)
    later(reopened, 6000)


def reopened():
    stage('opened again')
    finish()


def finish():
    save()
    QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))


try:
    import modo
    lx.eval('scene.new')
    scene = modo.Scene()
    sea = flat_mesh(scene, 'Sea Plane', 0.0)

    from moonray_modo import entities, layers, materials, node_defaults, nodes, ocean_meshes, properties
    from moonray_modo.material_override import synchronize
    lx.eval('select.item {%s} set' % sea.id)
    material = materials.assign('DwaBaseMaterial', name='Sea Water')
    if material is None:
        material = next(i for i in scene.iterItems('advancedMaterial') if i.name == 'MoonShine Material')
    material = modo.Item(material) if not isinstance(material, modo.Item) else material
    material.name = 'Sea Water'
    report['package_before_graph'] = sea.PackageTest(ocean_meshes.PACKAGE)
    graph = nodes.new('DwaBaseMaterial', {'albedo': [0.004, 0.018, 0.026], 'roughness': 0.03, 'refractive_index': 1.33, 'metallic': 0.0})
    graph['nodes']['sea'] = {'type': 'ocean', 'position': [-300, 300], 'inputs': {},
                             'parameters': {'tiles_across': 4.0, 'resolution': 512, 'wind_speed': 12.0, 'wind_direction': 30.0,
                                            'choppiness': 1.2, 'against_wind': 0.3, 'swell_height': 1.5, 'swell_length': 140.0,
                                            'swell_direction': 55.0}}
    graph['nodes']['waves'] = {'type': 'VectorDisplacement', 'position': [0, 300], 'inputs': {'vector': 'sea'},
                               'parameters': node_defaults.parameters('VectorDisplacement')}
    graph['displacement'] = 'waves'
    settings = properties.read(material)
    if os.environ.get('PROBE_OCEAN', '1') != '0':
        settings.update(native_shader='DwaBaseMaterial', node_graph=graph, node_override=True)
        properties.write(material, synchronize(settings, graph))
    else:
        report['ocean'] = False   # the same scene without its sea: a reopen that draws no points
    report['package_after_graph'] = sea.PackageTest(ocean_meshes.PACKAGE)
    report['material'] = material.id
    report['tag'] = tag = layers.material_tag(material)
    # A second plane wearing the same material by its tag alone (no material written): it has no package until the
    # scene is opened again.
    if os.environ.get('PROBE_SECOND', '1') != '0':
        second = flat_mesh(scene, 'Second Plane', 45.0)
        with second.geometry as geo:
            for polygon in geo.polygons:
                polygon.materialTag = tag
        report['second_package_before'] = second.PackageTest(ocean_meshes.PACKAGE)

    # An Ocean Plane under it, its material tag naming the plane's material.
    lx.eval('select.drop item')
    lx.eval('moonray.entity.add OceanPlaneGeometry')
    level = [i for i in scene.items() if i.type == 'moonray.OceanPlaneGeometry'][0]
    lx.eval('select.item {%s} set' % level.id)
    lx.eval('transform.channel pos.Y -4.0')
    level.channel(entities.CHANNEL_PREFIX + 'modo_material').set(tag)
    report['ocean_plane'] = level.id

    camera = scene.renderCamera
    lx.eval('select.item {%s} set' % camera.id)
    lx.eval('transform.channel pos.X 22.0')
    lx.eval('transform.channel pos.Y 40.0')
    lx.eval('transform.channel pos.Z 60.0')
    lx.eval('transform.channel rot.X -32.0')
    camera.channel('focalLen').set(0.035)
    lx.eval('select.drop item')
except Exception:
    report['errors'].append(traceback.format_exc())
save()
later(opened, 8000)
