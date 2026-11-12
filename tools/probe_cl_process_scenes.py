# python
"""Command-line: the Process scenes of probe_gui_process_layer.py (a slab glowing by a Constant under a Process layer, the
camera 3 units back) captured as the kit hands them to the renderers, for the cases that leave Bias and Gain alone, to
render outside Modo and compare with Modo's own renders (test-results/process-layer/measured.json; check_process_layer.py).
Writes test-results/process-layer/<case>.pickle."""
import json
import pathlib
import pickle
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\process-layer')
COLOURS = {'orange': (0.8, 0.3, 0.1), 'blue': (0.2, 0.5, 0.9)}
SETTINGS = {'none': {}, 'hue25': {'hue': 0.25}, 'sat-50': {'sat': -0.5}, 'val+50': {'val': 0.5}, 'shift25': {'hueShift': 0.25},
            'shift90deg': {'hueShift': 90.0}}
report = {}
try:
    from moonray_modo import host
    lx.eval('scene.new')
    scene = modo.Scene()
    mesh = scene.addMesh('Slab')
    geometry = modo.Mesh(mesh).geometry
    corners = [geometry.vertices.new(p) for p in ((-1, -.6, 0), (1, -.6, 0), (1, .6, 0), (-1, .6, 0))]
    geometry.polygons.new(corners)
    geometry.setMeshEdits()
    material = next(i for i in scene.items('advancedMaterial'))
    material.channel('diffAmt').set(0)
    material.channel('specAmt').set(0)
    material.channel('radiance').set(1)
    scene.select(material)
    lx.eval('shader.create constant')
    constant = next(i for i in scene.items('constant'))
    constant.channel('effect').set('lumiColor')
    scene.select(constant)
    lx.eval('shader.create process')
    process = next(i for i in scene.items('process'))
    process.channel('effect').set('lumiColor')
    camera = next(i for i in scene.items('camera'))
    modo.LocatorSuperType(camera).position.set((0, 0, 3))
    modo.LocatorSuperType(camera).rotation.set((0, 0, 0))
    for colour_name, colour in COLOURS.items():
        for axis, part in zip('RGB', colour):
            constant.channel('color.' + axis).set(part)
        for setting_name, values in SETTINGS.items():
            for key in ('hue', 'sat', 'val', 'hueShift'):
                process.channel(key).set(values.get(key, 0.0))
            case = colour_name + '_' + setting_name
            snapshot = host.snapshot()
            report[case] = [w for w in snapshot.get('warnings', []) if 'Process' in w or 'translator' in w]
            (out / (case + '.pickle')).write_bytes(pickle.dumps(snapshot, protocol=4))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'scenes.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
