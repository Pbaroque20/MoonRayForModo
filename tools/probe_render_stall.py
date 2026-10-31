# python
"""Isolated GUI test (tools/launch_gui_probe.py, a test profile): the Render button on the scene in MOONRAY_PROBE_SCENE, as it stands, no
realtime. A heartbeat on Modo's thread every 20 ms; where it stops for over 2 s, a watcher on another thread writes down where Modo's thread
is. Every status, the renderer's lines and how the render ended, into MOONRAY_PROBE_OUT/report.json, kept as it goes."""
import json
import os
import pathlib
import sys
import threading
import time
import traceback
import lx
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(os.environ['MOONRAY_PROBE_OUT'])
out.mkdir(parents=True, exist_ok=True)
LIMIT = float(os.environ.get('MOONRAY_PROBE_LIMIT', '400'))
result = {'stalls': [], 'where': [], 'status': [], 'lines': [], 'ended': None}
zero = time.perf_counter()
held = {'beat': None, 'ident': threading.get_ident(), 'done': False}
lock = threading.Lock()


def now():
    return round(time.perf_counter() - zero, 3)


def save():
    with lock:
        text = json.dumps(result, indent=1, default=str)
    (out / 'report.json').write_text(text, encoding='utf-8')


def beat():
    t = time.perf_counter()
    if held['beat'] is not None and t - held['beat'] > 0.2:
        with lock:
            result['stalls'].append((now(), round(t - held['beat'], 3)))
    held['beat'] = t


def watcher():
    """Where Modo's thread is while it does not beat, and what the others are doing."""
    told = None
    while not held['done']:
        time.sleep(0.5)
        last = held['beat']
        if last is None or time.perf_counter() - last < 2.0:
            told = None
            continue
        if told is not None and time.perf_counter() - told < 5.0:
            continue
        told = time.perf_counter()
        frames = sys._current_frames()
        main = frames.get(held['ident'])
        stack = [f.name + ':' + str(f.lineno) + ' ' + f.filename.rsplit('\\', 1)[-1] for f in traceback.extract_stack(main)[-14:]] if main else []
        others = {}
        for ident, frame in frames.items():
            if ident == held['ident'] or ident == threading.get_ident():
                continue
            others[str(ident)] = [f.name + ':' + str(f.lineno) + ' ' + f.filename.rsplit('\\', 1)[-1] for f in traceback.extract_stack(frame)[-5:]]
        with lock:
            result['where'].append({'at': now(), 'stopped': round(time.perf_counter() - last, 2), 'modo': stack, 'others': others})
        save()


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def skip_unknown(left=180):
    """Modo's question for items of a plugin the test profile has not (the car's Octane meshes): Yes to All."""
    try:
        (out / 'windows.txt').write_text('%.0f s: %s' % (now(), sorted({w.windowTitle() for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible() and w.windowTitle()})), encoding='utf-8')
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if widget.isVisible() and widget.windowTitle().startswith('Load Error'):
                for button in widget.findChildren(QtWidgets.QAbstractButton):
                    if button.text().replace('&', '').startswith('Yes to All'):
                        button.click()
    except Exception:
        pass
    if left > 0:
        QtCore.QTimer.singleShot(1000, lambda: skip_unknown(left - 1))


def finish():
    held['done'] = True
    save()
    lx.eval('!app.quit')


def begin():
    try:
        panel = panel_widget()
        held['panel'] = panel
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        if panel.ipr_mode.isChecked():
            panel.ipr_mode.setChecked(False)
        timer = QtCore.QTimer(panel)
        timer.setInterval(20)
        timer.timeout.connect(beat)
        timer.start()
        held['timer'] = timer

        def status(text):
            with lock:
                result['status'].append((now(), str(text)[:200]))
        panel.renderer.status.connect(status)
        panel.renderer.failed.connect(lambda text: status('FAILED: ' + str(text)))
        panel.renderer.session.output.connect(lambda text: [result['lines'].append((now(), l[:240])) for l in str(text).splitlines() if l.strip() and not l.startswith('@@MODO_')])
        threading.Thread(target=watcher, daemon=True).start()
        result['pressed'] = now()
        panel.start_render()
        result['pressed_back'] = now()
        QtCore.QTimer.singleShot(5000, look)
    except Exception:
        result['error'] = traceback.format_exc()
        finish()


def look():
    panel = held['panel']
    rendering = bool(getattr(panel, '_rendering', False))
    with lock:
        result.setdefault('looks', []).append((now(), rendering, panel.status.text()[:120]))
    save()
    if result.get('saw') is None and rendering:
        result['saw'] = now()
    if result.get('saw') is not None and not rendering:
        result['ended'] = now()
        finish()
        return
    if now() - result['pressed'] > LIMIT:
        result['ended'] = 'not within the limit'
        finish()
        return
    QtCore.QTimer.singleShot(2000, look)


try:
    save()
    skip_unknown()
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    result['opened'] = now()
    lx.eval('moonray.open')
except Exception:
    result['error_open'] = traceback.format_exc()
QtCore.QTimer.singleShot(8000, begin)
