# python
"""GUI: Modo Mesh Lights in Modo's own renderer and in every engine of the preview window. A grey floor, a grey ball
and above them two Mesh Lights (radiance 3, Visible to Camera on) whose shown Prototypes face down
toward the floor and the camera (a square, and an octagon beside a quad and a triangle); Modo's other lights and its environment off. Modo renders it first (modo.exr), then the
preview window in MoonRay Scalar, Vector, XPU, XPU2 and MoonLightIPR, each picture saved as shown (<engine>.png).
PROBE_SCENE, where set, is opened instead of the scene made here, and PROBE_OUT names the folder written to. Writes test-results/mesh-light-all-engines/."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(os.environ.get('PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\mesh-light-all-engines')
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}
held = {}
ENGINES = [('scalar', 'moonray', 'scalar', 'xpu'), ('vector', 'moonray', 'vectorized', 'xpu'), ('xpu', 'moonray', 'xpu', 'xpu'),
           ('xpu2', 'moonray', 'xpu', 'xpu2'), ('moonlightipr', 'moonlightipr', 'vectorized', 'xpu')]


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))


def quad(scene, name, size, up):
    mesh = scene.addMesh(name)
    with mesh.geometry as geo:
        points = [geo.vertices.new(p) for p in ((-size, 0, -size), (size, 0, -size), (size, 0, size), (-size, 0, size))]
        geo.polygons.new(list(reversed(points)) if up else points)
    return mesh


try:
    scene_file = os.environ.get('PROBE_SCENE')
    if scene_file:
        lx.eval('scene.open {%s} normal' % scene_file)
        scene = modo.Scene()
    else:
        scene = modo.Scene()
        quad(scene, 'Floor', 4.0, True)
        lx.eval('item.create mesh Ball')
        ball = next(i for i in scene.items('mesh') if i.name.startswith('Ball'))
        lx.eval('select.item {%s} set' % ball.id)
        lx.eval('tool.set prim.sphere on')
        lx.eval('tool.attr prim.sphere cenY 0.6')
        lx.eval('tool.attr prim.sphere sizeX 0.6'); lx.eval('tool.attr prim.sphere sizeY 0.6'); lx.eval('tool.attr prim.sphere sizeZ 0.6')
        lx.eval('tool.apply'); lx.eval('tool.set prim.sphere off')
        import math
        # Two Mesh Lights facing the camera: a square panel (two quads), and a mixed one (an octagon, a quad and a
        # triangle side by side), which shows whether faces of different sizes are read right.
        def prototype(name, faces_of, at):
            mesh = scene.addMesh(name)
            with mesh.geometry as geo:
                for corners in faces_of:
                    points = [geo.vertices.new(c) for c in corners]
                    geo.polygons.new(points)
            mesh.position.set(at)
            mesh.rotation.set((-0.6, 0.0, 0.0))
            return mesh
        square = [[(-0.5, 0, -0.5), (0, 0, -0.5), (0, 0, 0.5), (-0.5, 0, 0.5)], [(0, 0, -0.5), (0.5, 0, -0.5), (0.5, 0, 0.5), (0, 0, 0.5)]]
        octagon = [(-0.6 + 0.35 * math.cos(math.pi * k / 4), 0, 0.35 * math.sin(math.pi * k / 4)) for k in range(8)]
        mixed = [octagon, [(-0.15, 0, -0.3), (0.25, 0, -0.3), (0.25, 0, 0.3), (-0.15, 0, 0.3)], [(0.35, 0, -0.3), (0.75, 0, 0.0), (0.35, 0, 0.3)]]
        made = []
        for name, faces, at in (('Square', square, (-1.6, 1.9, -0.5)), ('Mixed', mixed, (1.4, 1.9, -0.5))):
            mesh = prototype(name, faces, at)
            before = {i.id for i in scene.items('meshLight', superType=False)}
            lx.eval('item.create meshLight')
            light = next(i for i in scene.items('meshLight', superType=False) if i.id not in before)
            light.name = name + ' Light'
            lx.eval('select.item {%s} set' % light.id)
            lx.eval('light.mesh mesh:{%s}' % mesh.id)
            light.channel('radiance').set(3.0)
            light.channel('visCam').set(1)
            made.append(mesh)
        for other in [i for i in scene.items('light') if i.type != 'meshLight']:
            other.channel('render').set('off')
        for environment in list(scene.items('environment')):
            scene.removeItems(environment)
        camera = scene.renderCamera or modo.Camera(next(iter(scene.items('camera'))))
        camera.position.set((0.0, 1.3, 6.5))
        camera.rotation.set((-0.08, 0.0, 0.0))
        render = scene.renderItem
        for name, value in (('resX', 640), ('resY', 360), ('first', 1), ('last', 1)):
            render.channel(name).set(value)
        lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'mesh_light_engines.lxo'))
    result['lights'] = {l.name: {n: l.channel(n).get() for n in ('radiance', 'visCam', 'visRefl', 'visRefr', 'useSrcXfrm')}
                        for l in scene.items('meshLight', superType=False)}
    from moonray_modo import host
    shot = host.snapshot()
    result['snapshot_lights'] = [{k: v for k, v in l.items() if k != 'shape'} for l in shot.get('lights') or []]
    result['snapshot_meshes'] = [m.get('name') for m in shot.get('meshes') or []]
    result['warnings'] = shot.get('warnings')
    save()
    # Modo's own render, the reference: the current frame alone (a scene opened with PROBE_SCENE keeps its own frame
    # range, and Modo rendered the whole of it). MOONRAY_PROBE_NO_MODO leaves it out, for MoonRay's own lights, which
    # Modo's renderer does not draw.
    if not os.environ.get('MOONRAY_PROBE_NO_MODO'):
        frame = int(round(lx.service.Selection().GetTime() * scene.fps))
        for name in ('first', 'last'):
            scene.renderItem.channel(name).set(frame)
        lx.eval('!render.animation {%s} openexr' % str(out / 'modo'))
    result['modo_render'] = [p.name for p in out.glob('modo*.exr')]
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def panel_widget():
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def render(index):
    if index >= len(ENGINES):
        return finish()
    label, engine, mode, renderer = ENGINES[index]
    try:
        p = panel_widget()
        p.preferences.set('xpu2/renderer', renderer)
        p._store(execution_mode=mode)
        p.preview_engine.setCurrentIndex(p.preview_engine.findData(engine))
        p.render_once()
        began = time.monotonic()

        def wait():
            try:
                q = panel_widget()
                if (getattr(q, '_rendering', False) and time.monotonic() - began < 240) or time.monotonic() - began < 6:
                    QtCore.QTimer.singleShot(1500, wait); return

                def grab():
                    QtWidgets.QApplication.processEvents()
                    q.preview.image.save(str(out / (label + '.png')))
                    q.window().grab().save(str(out / (label + '-window.png')))
                    result['steps'].append([label, q.status.text(), q.image_info.text(), q.render_timing.text()])
                    try:
                        from moonray_modo import terminal
                        said = [str(e[4]) for e in terminal.entries()][-40:]
                        result.setdefault('log', {})[label] = [s for s in said if 'ight' in s or 'rror' in s or 'arn' in s][-15:]
                    except Exception:
                        pass
                    save(); render(index + 1)
                QtCore.QTimer.singleShot(4000, grab)
            except Exception:
                result[label + '_wait_error'] = traceback.format_exc(); save(); render(index + 1)
        QtCore.QTimer.singleShot(2000, wait)
    except Exception:
        result[label + '_error'] = traceback.format_exc(); save(); render(index + 1)


def finish():
    try:
        panel_widget().stop()
    except Exception:
        result['finish_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(8000, lambda: render(0))
