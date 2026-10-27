# python
"""Isolated GUI test (tools/launch_gui_probe.py, a test profile): what MoonLightIPR does between an edit let go and its
picture changing. The scene in MOONRAY_PROBE_SCENE is followed by MoonLightIPR in realtime (the RT switch where the kit
has one); an item is moved five times by command, as a drag ends; each time the reading of the scene (panel._capture),
its digest, the packing (moonlightipr_scene.pack, on the session's thread), the submit, and the wait until the picture
changes are written down, into MOONRAY_PROBE_OUT/report.json."""
import json
import os
import pathlib
import threading
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(os.environ['MOONRAY_PROBE_OUT'])
out.mkdir(parents=True, exist_ok=True)
result = {'moves': [], 'kit': None}
held = {'events': []}
lock = threading.Lock()


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def note(kind, seconds=None):
    with lock:
        held['events'].append((round(time.perf_counter() - held.get('at', 0.0), 4), kind, None if seconds is None else round(seconds, 4),
                               threading.current_thread().name[:20]))


def wrap(owner, name, kind):
    original = getattr(owner, name)

    def timed(*a, **k):
        began = time.perf_counter()
        try:
            return original(*a, **k)
        finally:
            note(kind, time.perf_counter() - began)
    setattr(owner, name, timed)


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def key():
    image = panel_widget().preview.image
    return None if image.isNull() else image.cacheKey()


def begin():
    try:
        panel = panel_widget()
        from moonray_modo import moonlightipr_scene, scene_digest
        result['kit'] = moonlightipr_scene.__file__
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))
        QtWidgets.QApplication.processEvents()
        wrap(panel, '_capture', 'read scene')
        wrap(panel, '_capture_preview', 'read scene (motion)')
        wrap(panel, '_digest', 'digest')
        wrap(panel, '_submit', 'submit')
        wrap(moonlightipr_scene, 'pack', 'pack')
        held['item'] = next(m.id for m in modo.Scene().items('mesh'))
        if hasattr(panel, 'rt'):
            panel.rt.click()
        else:
            panel.start.click()
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(int(os.environ.get('MOONRAY_PROBE_SETTLE', '40')) * 1000, lambda: move(0))


def move(count):
    try:
        with lock:
            held['events'] = []
        held.update(before=key())
        lx.eval('select.item {%s} set' % held['item'])
        held['at'] = time.perf_counter()
        lx.eval('transform.channel pos.X %s' % (0.02 * (count + 1)))
        note('command done')
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    QtCore.QTimer.singleShot(5, lambda: moved(count))


def moved(count):
    waited = time.perf_counter() - held['at']
    if key() != held['before'] or waited > 30:
        with lock:
            events = list(held['events'])
        result['moves'].append({'to_new_picture': round(waited, 3), 'events': events})
        save()
        if count < 4:
            QtCore.QTimer.singleShot(4000, lambda: move(count + 1))
        else:
            finish()
        return
    QtCore.QTimer.singleShot(5, lambda: moved(count))


def finish():
    try:
        panel = panel_widget()
        if hasattr(panel, 'rt') and panel.rt.isChecked():
            panel.rt.click()
        panel.stop()
    except Exception:
        pass
    save()
    lx.eval('!app.quit')


try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    lx.eval('moonray.render.denoiser 0')
    lx.eval('moonray.open')
except Exception:
    result['error_open'] = traceback.format_exc()
QtCore.QTimer.singleShot(8000, begin)
