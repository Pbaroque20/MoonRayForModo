# python
"""Isolated GUI test: Draft with a region, rendered by MoonRay XPU and then by XPU2, to compare the two.

For each renderer (Preferences > MoonRay > XPU2: MoonRay XPU, then XPU2) with the scene in XPU mode: Draft on, a region
marked, Render pressed. Every half second the status, the picture's line, which renderer the session is, and what the
draft holds (its lines, the region's render and their sizes) are written down; at the end of each the window is
pictured. Writes test-results/draft-region-xpu2/report.json."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/draft-region-xpu2'
out.mkdir(parents=True, exist_ok=True)
REGION = [0.25, 0.25, 0.75, 0.75]
result = {'runs': {}}
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
    return [c.red(), c.green(), c.blue(), c.alpha()]


def state(panel):
    session = getattr(panel.renderer, 'session', None)
    part = panel._draft_render
    shown = panel.preview.image
    return {'status': panel.status.text(), 'info': panel.image_info.text(), 'timing': panel.render_timing.text(), 'button': panel.start.text(),
            'rendering': panel._rendering, 'xpu2_active': getattr(session, 'xpu2_active', None), 'xpu2_refused': getattr(session, 'xpu2_refused', None),
            'session_running': session.running() if session is not None and hasattr(session, 'running') else None,
            'draft_lines': None if panel._draft_image is None else [panel._draft_image.width(), panel._draft_image.height()],
            'draft_fine': list(panel._draft_fine), 'draft_quick': list(getattr(panel, '_draft_quick', (0, 0)) or (0, 0)),
            'region_render': None if part is None else {'region': part[0], 'size': [part[1].width(), part[1].height()],
                                                        'middle': colour(part[1], .5, .5), 'corner': colour(part[1], .05, .05)},
            'region_stored': panel._draft_region(), 'shown': [shown.width(), shown.height()], 'shown_middle': colour(shown, .5, .5),
            'shown_corner': colour(shown, .05, .05)}


def watch(name, left, then):
    panel = panel_widget()
    result['runs'][name].append(state(panel))
    save()
    if left > 0:
        QtCore.QTimer.singleShot(500, lambda: watch(name, left - 1, then))
    else:
        panel.window().grab().save(str(out / (name + '.png')))
        then()


def run(renderer, then):
    name = renderer
    result['runs'][name] = []
    try:
        panel = panel_widget()
        panel.preferences.set('xpu2/renderer', renderer)
        if panel.draft.isChecked():
            panel.draft.click()
        panel._store(execution_mode='xpu')
        panel._store(region=REGION, region_enabled=True)
        panel.draft.click()
        # The draft's lines first (the button reads Stop while they are drawn); then Render renders the region.
        # MOONRAY_PROBE_PRESS: render (the Render button, default) or rt (the RT switch). Waited for: the lines drawn
        # and the panel no longer rendering, up to half a minute, and said either way.
        which = __import__('os').environ.get('MOONRAY_PROBE_PRESS', 'render')
        # render_now: Render pressed while the draft's lines are still being drawn, as a person does.
        def press(left=60):
            if which != 'render_now' and (panel.start.text() != 'Render' or panel._rendering) and left > 0:
                QtCore.QTimer.singleShot(500, lambda: press(left - 1));return
            result['runs'][name].append({'pressed': which, 'button': panel.start.text(), 'before': state(panel)})
            if which == 'rt':panel.rt.click()
            else:panel.start.click()
            watch(name, 60, then)
        QtCore.QTimer.singleShot(300 if which == 'render_now' else 3000, press)
    except Exception:
        result['runs'][name].append({'error': traceback.format_exc()})
        save()
        then()


def finish():
    try:
        panel = panel_widget()
        if panel.draft.isChecked():
            panel.draft.click()
        panel.preferences.store.setValue('xpu2/renderer', held.get('renderer', 'xpu2'))
    except Exception:
        result['finish'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


def begin():
    try:
        panel = panel_widget()
        held['renderer'] = panel.preferences.store.value('xpu2/renderer', 'xpu2')
        if panel.ipr_mode.isChecked():
            panel.ipr_mode.setChecked(False)
        result['engine'] = panel.preview_engine.currentData()
        result['xpu2_shaders'] = __import__('moonray_modo.native', fromlist=['x']).xpu2_shaders_compiled()
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
