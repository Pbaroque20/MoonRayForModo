# python
"""Makes the car paint test scene: a simple car-like body in the library's Car paint (a DwaMetalMaterial with a coat and glitter
flakes), dark wheels and a floor, under a studio HDRI. Run through tools/launch_cl_probe.py. MOONRAY_PROBE_HDRI names the HDRI,
copied beside the scene. Writes test-results/car-paint-scene/car_paint.lxo, snapshot.pickle and report.json."""
import json
import math
import os
import pathlib
import pickle
import shutil
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/car-paint-scene'
out.mkdir(parents=True, exist_ok=True)
report = {}


def profile(x):
    """(half width, top) of the body at x along its length, nose at -2.2: low bonnet, a cabin, a boot."""
    t = (x + 2.2) / 4.4
    width = .86 * min(1.0, (math.sin(min(1.0, t / .16) * math.pi / 2) ** .5) * (math.sin(min(1.0, (1 - t) / .1) * math.pi / 2) ** .5)) + .02
    bonnet = .62 + .2 * min(1.0, t / .3)
    cabin = 1.3 * math.exp(-((t - .55) / .17) ** 4)
    return width, max(bonnet, cabin) if t < .85 else max(.82 - (t - .85) * .6, cabin)


def body(mesh):
    geometry = modo.Mesh(mesh).geometry
    stations, around = 64, 32
    rings = []
    for i in range(stations + 1):
        x = -2.2 + 4.4 * i / stations
        width, top = profile(x)
        ring = []
        for j in range(around):
            a = 2 * math.pi * j / around
            c, s = math.cos(a), math.sin(a)
            # A rounded box's section: flatter sides and top than an ellipse.
            z = width * math.copysign(abs(c) ** .45, c)
            y = .24 + (top - .24) * .5 * (1 + math.copysign(abs(s) ** .6, s))
            ring.append(geometry.vertices.new((x, y, z)))
        rings.append(ring)
    for i in range(stations):
        for j in range(around):
            k = (j + 1) % around
            # Facing out: MoonRay adds a DwaBase coat only where a ray enters the front of a face.
            geometry.polygons.new((rings[i + 1][j], rings[i + 1][k], rings[i][k], rings[i][j]))
    geometry.polygons.new(rings[0])
    geometry.polygons.new(list(reversed(rings[-1])))
    geometry.setMeshEdits()


def wheel(mesh, x, z):
    geometry = modo.Mesh(mesh).geometry
    sides, radius, width = 48, .34, .13
    near, far = [], []
    for j in range(sides):
        a = 2 * math.pi * j / sides
        near.append(geometry.vertices.new((x + radius * math.cos(a), .34 + radius * math.sin(a), z - width)))
        far.append(geometry.vertices.new((x + radius * math.cos(a), .34 + radius * math.sin(a), z + width)))
    for j in range(sides):
        k = (j + 1) % sides
        geometry.polygons.new((near[j], near[k], far[k], far[j]))
    geometry.polygons.new(list(reversed(near)))
    geometry.polygons.new(far)
    geometry.setMeshEdits()


def floor(mesh):
    geometry = modo.Mesh(mesh).geometry
    size = 30
    corners = [geometry.vertices.new(p) for p in ((-size, 0, -size), (-size, 0, size), (size, 0, size), (size, 0, -size))]
    geometry.polygons.new(corners)
    geometry.setMeshEdits()


def assign(mesh, values):
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('moonray.library.assign %s' % properties.encode(values))


try:
    from moonray_modo import host, properties
    lx.eval('scene.new')
    scene = modo.Scene()
    for light in list(scene.items('sunLight')):
        scene.removeItems([light])
    car, wheels, ground = scene.addMesh('Car body'), scene.addMesh('Wheels'), scene.addMesh('Floor')
    body(car)
    for x in (-1.35, 1.4):
        for z in (-.8, .8):
            wheel(wheels, x, z)
    floor(ground)
    preset = json.loads((root / 'kit/MoonRayForModo/assets/library/materials/Car paint.moonmat.json').read_text(encoding='utf-8'))
    assign(car, {'shader': preset['shader'], 'parameters': preset['parameters']})
    assign(wheels, {'shader': 'DwaBaseMaterial', 'parameters': {'albedo': [.02, .02, .02], 'roughness': .55}})
    assign(ground, {'shader': 'DwaBaseMaterial', 'parameters': {'albedo': [.18, .18, .19], 'roughness': .45}})

    hdri = out / 'studio_2k.exr'
    shutil.copyfile(os.environ['MOONRAY_PROBE_HDRI'], hdri)
    environment = next(iter(scene.items('environment')))
    lx.eval('clip.addStill {%s}' % hdri)
    clip = scene.items('videoStill')[-1]
    lx.eval('item.create imageMap')
    layer = scene.selected[0]
    lx.eval('texture.parent {%s} %d item:{%s}' % (environment.id, len(environment.children()), layer.id))
    lx.eval('select.item {%s} set' % layer.id)
    lx.eval('texture.setIMap {%s}' % clip.id)
    locator = next(i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
    locator.channel('projType').set('spherical')

    render = scene.renderItem
    for name, value in (('resX', 1280), ('resY', 720), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    camera = scene.renderCamera
    lx.eval('select.item {%s} set' % camera.id)
    eye = (-4.6, 1.15, 4.9)
    aim = (0.0, .55, 0.0)
    across = math.hypot(eye[0] - aim[0], eye[2] - aim[2])
    for axis, value in (('pos.X', eye[0]), ('pos.Y', eye[1]), ('pos.Z', eye[2]),
                        ('rot.X', -math.degrees(math.atan2(eye[1] - aim[1], across))),
                        ('rot.Y', math.degrees(math.atan2(eye[0] - aim[0], eye[2] - aim[2]))), ('rot.Z', 0)):
        lx.eval('transform.channel %s %s' % (axis, value))
    camera.channel('focalLen').set(.05)

    snapshot = host.snapshot()
    report['warnings'] = snapshot.get('warnings')
    report['meshes'] = [(m.get('name'), len(m.get('faces') or [])) for m in snapshot.get('meshes', [])]
    report['environments'] = len(snapshot.get('environments') or [])
    report['materials'] = {k: v.get('native_shader') for k, v in snapshot.get('materials', {}).items()}
    (out / 'snapshot.pickle').write_bytes(pickle.dumps(snapshot, protocol=4))
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'car_paint.lxo'))
    report['saved'] = (out / 'car_paint.lxo').is_file()
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
