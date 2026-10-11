# python
"""Isolated GUI test: a preview stopped by hand is kept as finished, and denoised where that is asked for.

A ball is previewed with Live off. With MoonLightIPR a render is started and stopped a moment later: it must end as a
finished render does, with a picture. With MoonRay a render is stopped once its first pass is in: the pass is kept and
the denoiser is asked for it."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/stop-finishes'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


try:
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def engine(name):
    panel = panel_widget()
    held.setdefault('stored', panel.preferences.store.value('runtime', ''))
    held.setdefault('engine', panel.preview_engine.currentData())
    held.setdefault('live', panel.ipr_mode.isChecked())
    panel.preferences.set('runtime', str(root / 'runtime/steady-0350-pool'))
    panel.ipr_mode.setChecked(False)
    if panel.start.text() == 'Stop':
        panel.start.click()
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(name))
    QtWidgets.QApplication.processEvents()
    return panel


def first():
    try:
        panel = engine('moonlightipr')
        panel.start.click()
    except Exception:
        result['first_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(15000, again)


def again():
    try:
        panel = panel_widget()
        result['moonlightipr_whole'] = [panel.status.text(), panel.start.text()]
        # A second render, stopped a moment after it begins.
        panel.start.click()
        QtCore.QTimer.singleShot(250, stop_it)
    except Exception:
        result['again_error'] = traceback.format_exc()
        save()
        QtCore.QTimer.singleShot(100, moonray)


def stop_it():
    try:
        panel = panel_widget()
        result['moonlightipr_before_stop'] = [panel.status.text(), panel.start.text(), panel._rendering]
        panel.start.click()
        result['moonlightipr_at_stop'] = [panel.status.text(), panel.start.text()]
    except Exception:
        result['stop_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(4000, moonray)


def moonray():
    try:
        panel = panel_widget()
        result['moonlightipr_after_stop'] = [panel.status.text(), panel.start.text(), panel._rendering, not panel.preview.image.isNull(), panel.buffer.currentText()]
        panel.window().grab().save(str(out / 'moonlightipr_stopped.png'))
        panel = engine('moonray')
        panel.start.click()
    except Exception:
        result['moonray_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(1500, watch)


def watch():
    """Stop MoonRay as soon as a pass of this render has been handed over."""
    try:
        panel = panel_widget()
        held['ticks'] = held.get('ticks', 0) + 1
        frame = panel.renderer.buffers.frame
        passed = bool(frame and frame.get('backend', '').lower().find('moonlight') < 0 and 'beauty' in frame.get('files', {}))
        if (passed and panel._rendering) or held['ticks'] > 80:
            result['moonray_before_stop'] = [panel.status.text(), panel._rendering, held['ticks'], sorted(frame.get('files', {})) if frame else None]
            panel.start.click()
            result['moonray_at_stop'] = [panel.status.text(), panel.start.text()]
            save()
            QtCore.QTimer.singleShot(25000, last)
            return
    except Exception:
        result['watch_error'] = traceback.format_exc()
        save()
        QtCore.QTimer.singleShot(100, last)
        return
    QtCore.QTimer.singleShot(500, watch)


def last():
    try:
        panel = panel_widget()
        frame = panel.renderer.buffers.frame or {}
        result['moonray_after_stop'] = [panel.status.text(), panel.start.text(), panel.buffer.currentText(), 'denoised_beauty' in frame.get('files', {}), panel.warnings.toPlainText()[:200]]
        panel.window().grab().save(str(out / 'moonray_stopped.png'))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(held['engine']))
        panel.preferences.store.setValue('runtime', held['stored'])
        panel.ipr_mode.setChecked(held['live'])
    except Exception:
        result['last_error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')


QtCore.QTimer.singleShot(5000, first)
