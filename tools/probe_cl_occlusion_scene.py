# python
"""Command-line: the floor and wall of probe_gui_occlusion_layer.py with the floor cut into 128 strips across (the kit
works occlusion out at a mesh's points), the same camera and Occlusion layer, captured as the kit hands it to the
renderers for the cases 'default' and 'dist1', to render outside Modo beside Modo's own renders
(check_occlusion_layer.py). Writes test-results/occlusion-layer/<case>.pickle and scenes.json."""
import json
import math
import pathlib
import pickle
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\occlusion-layer')
CASES = {'default': {}, 'dist1': {'dist': 1.0}}
report = {}
try:
    from moonray_modo import host
    lx.eval('scene.new')
    scene = modo.Scene()
    mesh = scene.addMesh('Corner')
    geometry = modo.Mesh(mesh).geometry
    columns = 128
    grid = [[geometry.vertices.new((4.0 * i / columns, 0, -2 + 4.0 * j / 4)) for j in range(5)] for i in range(columns + 1)]
    for i in range(columns):
        for j in range(4):
            geometry.polygons.new((grid[i][j], grid[i][j + 1], grid[i + 1][j + 1], grid[i + 1][j]))
    wall = [geometry.vertices.new(p) for p in ((0, 0, -2), (0, 4, -2), (0, 4, 2), (0, 0, 2))]
    geometry.polygons.new(wall)
    geometry.setMeshEdits()
    material = next(i for i in scene.items('advancedMaterial'))
    material.channel('diffAmt').set(0)
    material.channel('specAmt').set(0)
    material.channel('radiance').set(1)
    scene.select(material)
    lx.eval('shader.create occlusion')
    layer = next(i for i in scene.items('occlusion'))
    layer.channel('effect').set('lumiColor')
    layer.channel('rays').set(256)
    camera = next(i for i in scene.items('camera'))
    modo.LocatorSuperType(camera).position.set((2, 30, 0))
    modo.LocatorSuperType(camera).rotation.set((-math.pi / 2, 0, 0))
    camera.channel('focalLen').set(30 * 0.036 / 5.0)
    render = scene.renderItem
    for name, value in (('resX', 256), ('resY', 64)):
        render.channel(name).set(value)
    for case, values in CASES.items():
        layer.channel('dist').set(values.get('dist', 0.2))
        snapshot = host.snapshot()
        meshes = snapshot.get('meshes', [])
        report[case] = {'warnings': [w for w in snapshot.get('warnings', []) if 'cclusion' in w],
                        'weights': [sorted((m.get('point_attributes') or {}).keys()) for m in meshes]}
        (out / ('occ_' + case + '.pickle')).write_bytes(pickle.dumps(snapshot, protocol=4))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'scenes.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
