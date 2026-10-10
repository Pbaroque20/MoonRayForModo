# python
"""Isolated GUI test: a mesh is baked to a texture, as Bake Selected Mesh to Texture does it.

A cube stands on a ground under Modo's own light. The cube is baked at 512 pixels through the preview window's own
render, and the picture's size and how much of it is lit are written down, with a copy to look at."""
import json
import pathlib
import subprocess
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/bake'
out.mkdir(parents=True, exist_ok=True)
for old in list(out.glob('*.exr')) + list(out.glob('*.png')):
    old.unlink()
result = {}
held = {}
runtime = root / 'runtime/steady-0350-pool'


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def shape(name, **values):
    lx.eval('select.typeFrom item')
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    for key, value in values.items():
        lx.eval('tool.attr prim.cube %s %s' % (key, value))
    try:
        lx.eval('tool.attr prim.cube uvs true')
    except RuntimeError as exc:
        result['uvs_attr'] = str(exc)
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    mesh = modo.Scene().selected[0]
    mesh.name = name
    return mesh


try:
    shape('Ground', cenX=0, cenY=-.05, cenZ=0, sizeX=10, sizeY=.1, sizeZ=10)
    held['cube'] = shape('Crate', cenX=0, cenY=.5, cenZ=0, sizeX=1, sizeY=1, sizeZ=1)
    result['in_the_menu'] = 'moonray.page bake' in (root / 'kit/MoonRayForModo/layout.cfg').read_text(encoding='utf-8')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def bake_it():
    try:
        from moonray_modo import bake
        panel = panel_widget()
        held['stored'] = panel.preferences.store.value('runtime', '')
        panel.preferences.set('runtime', str(runtime))
        panel.stop()
        taken = panel._capture_output()
        result['has_uvs'] = {m.get('name'): bool(m.get('uvs') or m.get('uv_sets')) for m in taken['meshes']}
        scene = bake.scene(taken, held['cube'].id, 512)
        result['size_asked'] = [scene['width'], scene['height']]
        panel._submit(scene, str(out / 'crate.exr'))
    except Exception:
        result['bake_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(60000, look)


def look():
    try:
        from moonray_modo import native
        panel = panel_widget()
        result['status'] = [panel.status.text(), panel.warnings.toPlainText()[:400]]
        picture = out / 'crate.exr'
        result['written'] = picture.is_file()
        if picture.is_file():
            env = native.environment(runtime)
            done = subprocess.run([str(runtime / 'oiiotool.exe'), '--stats', str(picture)], env=env, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            result['stats'] = [line.strip() for line in (done.stdout + done.stderr).splitlines() if any(word in line for word in (' x ', 'Stats Avg', 'Stats Max', 'Constant'))][:6]
            subprocess.run([str(runtime / 'oiiotool.exe'), str(picture), '--ch', 'R,G,B', '--colorconvert', 'linear', 'sRGB', '-o', str(out / 'crate.png')], env=env,
                           capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        panel.preferences.store.setValue('runtime', held['stored'])
    except Exception:
        result['look_error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')


QtCore.QTimer.singleShot(5000, bake_it)
