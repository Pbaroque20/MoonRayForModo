# python
"""GUI: the tester's report of 2026-11-11, in Modo itself.
1. Convert to MoonRay Rect Light: an area light selected, the Item List's right-click menu (Modo's own item menu,
   06236135193:sheet) opened as a popover and grabbed as a picture, its entries listed; then the conversion run as the
   menu runs it, and the item read back.
2. Render missing frames: MoonRay renders frames 1 and 2 of an unsaved scene into a folder; then 1 to 4 with Render
   missing frames on (only 3 and 4 must be rendered, 1 and 2 untouched); then 1 to 4 again without it (refused).
Writes test-results/tester-1111/report.json and context-menu.png."""
import json
import os
import pathlib
import shutil
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tester-1111')
frames = out / 'frames'
if out.exists():
    shutil.rmtree(out, ignore_errors=True)
frames.mkdir(parents=True, exist_ok=True)
report = {}
state = {}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def panel():
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def step(fn, wait=500):
    def run():
        try:
            fn()
        except Exception:
            report.setdefault('errors', []).append(traceback.format_exc())
            save()
            finish()
    QtCore.QTimer.singleShot(wait, run)


# ---- the scene, at the top level (scene edits from a timer do not take) ------------------------------------------
lx.eval('scene.new')
scene = modo.Scene()
floor = scene.addMesh('Floor')
with floor.geometry as geo:
    v = [geo.vertices.new((x, 0.0, z)) for x, z in ((-3, -3), (3, -3), (3, 3), (-3, 3))]
    geo.polygons.new(v)
ball = scene.addMesh('Box')
with ball.geometry as geo:
    c = [geo.vertices.new((a - .4, b, d - .4)) for a in (0, .8) for b in (0, .8) for d in (0, .8)]
    for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
        geo.polygons.new([c[i] for i in face])
light = scene.addItem('areaLight', name='Key Area')
light.position.set((0.0, 2.5, 1.5))
light.rotation.set((-1.0, 0.0, 0.0))
light.channel('radiance').set(4.0)
camera = next(i for i in scene.items('camera'))
camera.position.set((0.0, 1.5, 5.0))
camera.rotation.set((-0.25, 0.0, 0.0))
render = scene.renderItem
for name, value in (('resX', 160), ('resY', 90)):
    render.channel(name).set(value)
scene.select(light)
lx.eval('moonray.open')


def context_menu():
    """Modo's item menu for the selection, as a right-click in the Item List opens it."""
    grabbed = {}

    def grab():
        popup = QtWidgets.QApplication.activePopupWidget() or QtWidgets.QApplication.activeModalWidget()
        if popup is None:
            grabbed['note'] = 'no popup'
            return
        popup.grab().save(str(out / 'context-menu.png'))
        grabbed['size'] = [popup.width(), popup.height()]
        popup.close()
    QtCore.QTimer.singleShot(2500, grab)
    try:
        lx.eval('attr.formPopover {06236135193:sheet}')
    except Exception as exc:
        grabbed['popover_error'] = str(exc)
    report['context_menu'] = grabbed
    save()
    step(convert, 3500)


def convert():
    selected = [i.type for i in modo.Scene().selected]
    lx.eval('moonray.light.convert')
    made = [i for i in modo.Scene().items() if i.name == 'Key Area']
    report['convert'] = {'selected_before': selected,
                         'after': [{'type': i.type, 'id': i.id} for i in made],
                         'area_lights_left': len(list(modo.Scene().items('areaLight')))}
    save()
    step(render_first, 1000)


def sequence(first, last, missing):
    from moonray_modo.animation import Sequence
    p = panel()
    p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonray'))
    run = Sequence(p, str(frames), first, last, float(modo.Scene().fps), False, 1, 'probe', missing, None, 4)
    state['sequence'] = run
    state['began'] = time.monotonic()
    run.start()
    return run


def files():
    return {f.name: f.stat().st_mtime for f in frames.glob('probe.*.exr')}


def render_first():
    sequence(1, 2, False)
    step(lambda: wait('first', render_more), 2000)


def wait(label, then):
    run = state['sequence']
    if run.running and time.monotonic() - state['began'] < 300:
        step(lambda: wait(label, then), 1000)
        return
    report[label] = {'seconds': round(time.monotonic() - state['began'], 1), 'files': files(), 'status': panel().status.text(),
                     'completed': [c.get('frame') for c in run.completed]}
    save()
    step(then, 1000)


def render_more():
    state['before'] = files()
    try:
        sequence(1, 4, True)
        report['missing_notices'] = list(getattr(state['sequence'], 'notices', []))
        step(lambda: wait('missing', refused), 2000)
    except Exception as exc:
        report['missing_refused'] = str(exc)
        save()
        step(refused, 500)


def refused():
    after = report.get('missing', {}).get('files', {})
    report['kept_untouched'] = {name: after.get(name) == when for name, when in state.get('before', {}).items()}
    try:
        sequence(1, 4, False)
        report['without_missing'] = 'not refused'
    except Exception as exc:
        report['without_missing'] = 'refused: ' + str(exc)
    save()
    finish()


def finish():
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


# PROBE_MENU=1: try to grab Modo's item menu as a picture first (a popover opened from a script).
step(context_menu if os.environ.get('PROBE_MENU') == '1' else convert, 8000)
