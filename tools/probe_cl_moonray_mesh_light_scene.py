# python
"""Command line: a scene with the kit's MoonRay MeshLight items (moonray.MeshLight), for rendering in every engine with
tools/probe_mesh_light_all_engines.py (PROBE_SCENE). A grey floor and ball; above them two meshes facing down, a
square (two quads) and an octagon beside a quad and a triangle, each named by a MeshLight item (intensity 3, Visible
in Camera on); Modo's own lights and environment off. Saved as test-results/moonray-mesh-light/scene.lxo."""
import json
import math
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\moonray-mesh-light')
out.mkdir(parents=True, exist_ok=True)
report = {}


def mesh(scene, name, faces, at=(0, 0, 0), turn=0.0):
    made = scene.addMesh(name)
    with made.geometry as geo:
        for corners in faces:
            geo.polygons.new([geo.vertices.new(c) for c in corners])
    made.position.set(at)
    made.rotation.set((turn, 0.0, 0.0))
    return made


try:
    from moonray_modo import entities
    scene = modo.Scene()
    mesh(scene, 'Floor', [[(-4, 0, -4), (-4, 0, 4), (4, 0, 4), (4, 0, -4)]])
    lx.eval('item.create mesh Ball')
    ball = next(i for i in scene.items('mesh') if i.name.startswith('Ball'))
    lx.eval('select.item {%s} set' % ball.id)
    lx.eval('tool.set prim.sphere on')
    for name, value in (('cenY', .6), ('sizeX', .6), ('sizeY', .6), ('sizeZ', .6)):
        lx.eval('tool.attr prim.sphere %s %s' % (name, value))
    lx.eval('tool.apply'); lx.eval('tool.set prim.sphere off')
    square = [[(-0.5, 0, -0.5), (0, 0, -0.5), (0, 0, 0.5), (-0.5, 0, 0.5)], [(0, 0, -0.5), (0.5, 0, -0.5), (0.5, 0, 0.5), (0, 0, 0.5)]]
    octagon = [(-0.6 + 0.35 * math.cos(math.pi * k / 4), 0, 0.35 * math.sin(math.pi * k / 4)) for k in range(8)]
    mixed = [octagon, [(-0.15, 0, -0.3), (0.25, 0, -0.3), (0.25, 0, 0.3), (-0.15, 0, 0.3)], [(0.35, 0, -0.3), (0.75, 0, 0.0), (0.35, 0, 0.3)]]
    mesh(scene, 'SquarePanel', square, (-1.6, 1.9, -0.5), -0.6)
    mesh(scene, 'MixedPanel', mixed, (1.4, 1.9, -0.5), -0.6)
    channels = {}
    for name, target in (('Square Glow', 'SquarePanel'), ('Mixed Glow', 'MixedPanel')):
        light = scene.addItem(entities.item_type('MeshLight'), name=name)
        light.channel(entities.CHANNEL_PREFIX + 'geometry').set(target)
        light.channel(entities.CHANNEL_PREFIX + 'intensity').set(3.0)
        channels[name] = {c.name: str(c.get())[:40] for c in light.channels() if c.name.startswith(entities.CHANNEL_PREFIX)}
    report['channels'] = channels
    for other in [i for i in scene.items('light')]:
        other.channel('render').set('off')
    for environment in list(scene.items('environment')):
        scene.removeItems(environment)
    camera = scene.renderCamera
    camera.position.set((0.0, 1.3, 6.5))
    camera.rotation.set((-0.08, 0.0, 0.0))
    render = scene.renderItem
    for name, value in (('resX', 640), ('resY', 360)):
        render.channel(name).set(value)
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'scene.lxo'))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
