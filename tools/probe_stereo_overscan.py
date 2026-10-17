# python
"""Isolated GUI test: Render EXR through a stereo camera with overscan.

The render camera is set to stereo, both eyes, a red-cyan composite and an overscan of 1.2, over a box on a floor.
Render EXR is chosen in the preview window, its file dialog answered with a path in test-results; the left eye, the
right eye and their composite are waited for, and each file's display and data windows written down."""
import json
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/stereo-overscan'
out.mkdir(parents=True, exist_ok=True)
for old in out.glob('shot*'):
    old.unlink()
target = out / 'shot.exr'
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def windows(path):
    import subprocess
    from moonray_modo import native
    runtime = native.find_runtime(held['panel'].runtime_path())
    done = subprocess.run([str(runtime / 'oiiotool.exe'), '--info', '-v', str(path)], env=native.environment(runtime),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return [line.strip() for line in done.stdout.decode(errors='replace').splitlines()
            if 'origin' in line or 'display size' in line or ' x ' in line][:4]


def check():
    files = {name: out / name for name in ('shot_left.exr', 'shot_right.exr', 'shot.exr')}
    result['seen'] = {name: path.is_file() for name, path in files.items()}
    if all(result['seen'].values()) or time.time() - held['start'] > 900:
        result['seconds'] = round(time.time() - held['start'])
        result['status'] = held['panel'].status.text()
        for name, path in files.items():
            if path.is_file():
                result[name] = windows(path)
        save()
        QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))
        return
    save()
    QtCore.QTimer.singleShot(2000, check)


def begin():
    try:
        panel = held['panel'] = panel_widget()
        panel._save_path = lambda *args, **kwargs: str(target)
        held['start'] = time.time()
        panel.render_final()
        result['started'] = panel.status.text()
    except Exception:
        result['error'] = traceback.format_exc()
        save()
        QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))
        return
    QtCore.QTimer.singleShot(2000, check)


try:
    scene = modo.Scene()
    floor = scene.addMesh('Floor')
    with floor.geometry as geometry:
        points = [geometry.vertices.new(p) for p in ((-4, 0, -4), (4, 0, -4), (4, 0, 4), (-4, 0, 4))]
        geometry.polygons.new(points[::-1])
    box = scene.addMesh('Box')
    corners = [(a - .5, b, c - .5) for a in (0, 1) for b in (0, 1) for c in (0, 1)]
    with box.geometry as geometry:
        points = [geometry.vertices.new(p) for p in corners]
        for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            geometry.polygons.new([points[i] for i in face])
    render = scene.renderItem
    render.channel('resX').set(320)
    render.channel('resY').set(180)
    camera = scene.renderCamera
    placed = modo.LocatorSuperType(camera)
    placed.position.set((0.0, 1.2, 4.0))
    placed.rotation.set((-0.2, 0.0, 0.0))
    for name, value in (('stereo', True), ('stereoEye', 'both'), ('stereoComp', 'anaRedCyan'), ('ioDist', 0.2),
                        ('convDist', 4.0), ('overscan', 1.2)):
        camera.channel(name).set(value)
    result['camera'] = {name: camera.channel(name).get() for name in ('stereo', 'stereoEye', 'stereoComp', 'overscan')}
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
