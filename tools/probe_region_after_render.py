# python
"""Isolated GUI test: a region drawn after a full render, then rendered, with MoonRay XPU and with XPU2.

For each renderer (Preferences > MoonRay > XPU2: MoonRay XPU, then XPU2), with the scene in XPU mode and Draft off: a full
render; then a region drawn as the Region tool draws one (Panel._region_drawn) and Render pressed; then the region
moved and Render pressed again. After each the status, the picture's line, the Terminal's engine and pixels inside and
outside the region are written down, and the window pictured. MOONRAY_PROBE_DRAFT=1 does the same with Draft on.
Writes test-results/region-after-render/report.json."""
import json
import os
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/region-after-render'
out.mkdir(parents=True, exist_ok=True)
DRAFT = os.environ.get('MOONRAY_PROBE_DRAFT') == '1'
result = {'draft': DRAFT, 'runs': {}}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def colour(image, x, y):
    if image is None or image.isNull():
        return None
    c = QtGui.QColor(image.pixel(min(image.width() - 1, int(x * image.width())), min(image.height() - 1, int(y * image.height()))))
    return [c.red(), c.green(), c.blue()]


def note(name, step):
    panel = panel_widget()
    image = panel.preview.image
    session = getattr(panel.renderer, 'session', None)
    entry = {'step': step, 'status': panel.status.text(), 'info': panel.image_info.text(), 'timing': panel.render_timing.text(),
             'rendering': panel._rendering, 'draft': panel.draft.isChecked(), 'xpu2_active': getattr(session, 'xpu2_active', None),
             'xpu2_refused': getattr(session, 'xpu2_refused', None), 'region': panel._draft_region(),
             'size': [image.width(), image.height()], 'samples': {k: colour(image, *xy) for k, xy in
                                                                 (('in_first', (.3, .3)), ('in_second', (.7, .7)), ('out_corner', (.03, .03)),
                                                                  ('out_middle_left', (.05, .5)))}}
    result['runs'][name].append(entry)
    panel.window().grab().save(str(out / ('%s-%s.png' % (name, step))))
    save()


def when_idle(then, left=240):
    """Once the render is done: the button reads Render and the panel is not rendering (up to two minutes)."""
    panel = panel_widget()
    if (panel._rendering or panel.start.text() != 'Render') and left > 0:
        QtCore.QTimer.singleShot(500, lambda: when_idle(then, left - 1));return
    then()


def run(renderer, then):
    name = renderer
    result['runs'][name] = []
    panel = panel_widget()

    def full():
        panel.preferences.set('xpu2/renderer', renderer)
        panel._store(execution_mode='xpu', region=[0.0, 0.0, 1.0, 1.0], region_enabled=False)
        panel.preview.set_region(None, False)
        if panel.draft.isChecked() != DRAFT:panel.draft.click()
        QtCore.QTimer.singleShot(1500, lambda: (panel.start.click() if not DRAFT else None, QtCore.QTimer.singleShot(3000, lambda: when_idle(first))))

    def first():
        note(name, '1-full')
        panel._region_drawn(0.2, 0.2, 0.45, 0.45)
        note(name, '2-drawn')
        panel.start.click()
        QtCore.QTimer.singleShot(3000, lambda: when_idle(second))

    def second():
        note(name, '3-first-region')
        panel._region_drawn(0.55, 0.55, 0.85, 0.85)
        panel.start.click()
        QtCore.QTimer.singleShot(3000, lambda: when_idle(done))

    def done():
        note(name, '4-second-region')
        then()

    try:
        full()
    except Exception:
        result['runs'][name].append({'error': traceback.format_exc()});save();then()


def finish():
    try:
        panel = panel_widget()
        panel.preferences.store.setValue('xpu2/renderer', held.get('renderer', 'xpu2'))
    except Exception:
        result['finish'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


def begin():
    try:
        panel = panel_widget()
        held['renderer'] = panel.preferences.store.value('xpu2/renderer', 'xpu2')
        if panel.ipr_mode.isChecked():panel.ipr_mode.setChecked(False)
    except Exception:
        result['begin'] = traceback.format_exc()
    save()
    run('xpu', lambda: run('xpu2', finish))


try:
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
