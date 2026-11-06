# python
"""Command line: a scene for a mesh light hidden from the camera but seen in reflections (Object controls' MoonRay
camera appearance). A mirror floor, a grey ball, and two square panels above facing down and toward the camera, each
made an emitter in Object controls: the left one 'Hidden; keep illumination', the right one 'Show emitter'. Modo's
lights and environment off. Saved as test-results/mesh-light-hidden/mesh_light_hidden.lxo, for
tools/probe_mesh_light_all_engines.py (PROBE_SCENE, MOONRAY_PROBE_NO_MODO)."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\mesh-light-hidden')
out.mkdir(parents=True, exist_ok=True)
report = {}


def quad(scene, name, size, up, at=(0, 0, 0), tilt=0.0, material=None):
    mesh = scene.addMesh(name)
    with mesh.geometry as geo:
        points = [geo.vertices.new(p) for p in ((-size, 0, -size), (size, 0, -size), (size, 0, size), (-size, 0, size))]
        geo.polygons.new(list(reversed(points)) if up else points)
    mesh.position.set(at)
    mesh.rotation.set((tilt, 0.0, 0.0))
    if material:
        lx.eval('select.item {%s} set' % mesh.id)
        lx.eval('select.type polygon')
        lx.eval('select.all')
        lx.eval('poly.setMaterial {%s}' % material)
        lx.eval('select.type item')
    return mesh


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    quad(scene, 'Floor', 4.0, True, material='Mirror')
    mirror = next(m for m in scene.items('mask', superType=False) if m.channel('ptag').get() == 'Mirror')
    material = next(c for c in mirror.children() if c.type == 'advancedMaterial')
    for name, value in (('diffAmt', 0.05), ('reflAmt', 0.9), ('specAmt', 0.9), ('rough', 0.02)):
        material.channel(name).set(value)
    lx.eval('item.create mesh Ball')
    ball = next(i for i in scene.items('mesh') if i.name.startswith('Ball'))
    lx.eval('select.item {%s} set' % ball.id)
    lx.eval('tool.set prim.sphere on')
    for key, value in (('cenY', 0.6), ('sizeX', 0.6), ('sizeY', 0.6), ('sizeZ', 0.6)):
        lx.eval('tool.attr prim.sphere %s %s' % (key, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    lx.eval('select.type item')
    hidden = quad(scene, 'Hidden Panel', 0.5, False, (-1.6, 1.9, -0.5), -0.6)
    shown = quad(scene, 'Shown Panel', 0.5, False, (1.6, 1.9, -0.5), -0.6)
    for other in scene.items('light'):
        other.channel('render').set('off')
    for environment in list(scene.items('environment')):
        scene.removeItems(environment)
    camera = scene.renderCamera
    camera.position.set((0.0, 1.5, 7.0))
    camera.rotation.set((-0.25, 0.0, 0.0))
    camera.channel('focalLen').set(0.025)
    render = scene.renderItem
    for name, value in (('resX', 640), ('resY', 360), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    from moonray_modo import properties
    settings = properties.scene_settings()
    objects = settings.setdefault('production', {}).setdefault('objects', {})
    objects[hidden.id] = {'mesh_light': True, 'light_intensity': 3.0, 'mesh_camera_mode': 'hidden'}
    objects[shown.id] = {'mesh_light': True, 'light_intensity': 3.0, 'mesh_camera_mode': 'emitter'}
    properties.write(render, settings)
    report['objects'] = properties.scene_settings().get('production', {}).get('objects')
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'mesh_light_hidden.lxo'))
    report['saved'] = True
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
