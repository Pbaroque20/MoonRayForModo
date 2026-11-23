# python
"""Isolated GUI test: XPU2 RT in Modo while the render camera is dragged, Rhea's engine or XPU2's (rhea/DESIGN.md 26).

A scene (MOONRAY_PROBE_SCENE) with XPU2 RT on and Follow drags on (the probe's own test preferences, put back at the end),
the RT engine MOONRAY_PROBE_RT_ENGINE (rhea or xpu2). Phases: the scene's first picture at rest (MOONRAY_PROBE_REST
seconds), the render camera dragged (moved every 30 ms by MOONRAY_PROBE_STEP along X for MOONRAY_PROBE_SPAN seconds, the
mouse held as far as the kit can tell), and the release (MOONRAY_PROBE_RELEASE seconds). Recorded: each move, every call
of the preview's tick on Modo's thread (timed and profiled), every render the kit asked for, every picture the session
handed over (when), and the session's own lines about Rhea, its frames and anything that went wrong. Written to
test-results/rhea/modo-drag/<MOONRAY_PROBE_TAG>/report.json, then Modo quits."""
import cProfile
import io
import json
import os
import pathlib
import pstats
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(os.environ.get('MOONRAY_PROBE_ROOT', r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\bvd-realtime-b5ce9a'))
out = root / 'test-results/rhea/modo-drag' / os.environ.get('MOONRAY_PROBE_TAG', 'run')
out.mkdir(parents=True, exist_ok=True)
REST = float(os.environ.get('MOONRAY_PROBE_REST', '3'))
SPAN = float(os.environ.get('MOONRAY_PROBE_SPAN', '4'))
RELEASE = float(os.environ.get('MOONRAY_PROBE_RELEASE', '5'))
STEP = float(os.environ.get('MOONRAY_PROBE_STEP', '0.01'))
T0 = time.perf_counter()
result = {'engine': os.environ.get('MOONRAY_PROBE_RT_ENGINE', 'rhea'), 'moves': [], 'ticks': [], 'submits': [], 'pictures': [],
          'session': [], 'phases': {}}
held = {'mover': None, 'profile': None, 'kept': {}}


def now():
    return round(time.perf_counter() - T0, 4)


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def begin():
    # The preview panel, once Modo has opened it (a minute at most).
    try:
        panel_widget()
    except StopIteration:
        held['waits'] = held.get('waits', 0) + 1
        if held['waits'] < 60:
            QtCore.QTimer.singleShot(1000, begin)
            return
    result['panel_found_after_s'] = now()
    try:
        import faulthandler
        held['crash'] = open(str(out / 'crash.txt'), 'wb', 0)
        faulthandler.enable(file=held['crash'], all_threads=True)
        panel = panel_widget()
        store = panel.preferences.store
        for key in ('xpu2/rt_engine', 'xpu2/follow_drags', 'xpu2/renderer'):
            held['kept'][key] = store.value(key)
        panel.preferences.set('xpu2/renderer', 'xpu2')
        panel.preferences.set('xpu2/rt_engine', result['engine'])
        panel.preferences.set('xpu2/follow_drags', True)
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        QtWidgets.QApplication.processEvents()
        tick, submit = panel._live_tick, panel.renderer.submit

        def timed():
            started = time.perf_counter()
            if held['profile'] is not None:
                held['profile'].enable()
            try:
                return tick()
            finally:
                if held['profile'] is not None:
                    held['profile'].disable()
                result['ticks'].append([now(), round(1000 * (time.perf_counter() - started), 2)])

        def counted(*a, **k):
            result['submits'].append([now(), bool(a and isinstance(a[0], dict) and a[0].get('_drag'))])
            return submit(*a, **k)
        panel._live_tick, panel.renderer.submit = timed, counted
        panel.timer.timeout.disconnect()
        panel.timer.timeout.connect(timed)
        result['tick_interval_ms'] = panel.timer.interval()
        held['camera'] = modo.Scene().renderCamera.id
        if not panel.rt.isChecked():
            panel.rt.click()
        result['rt_on_at'] = now()
        result['xpu2_drags'] = panel._xpu2_drags()
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    # The session's pictures and lines, once it is there; the drag once the first picture has been shown for REST
    # seconds (two minutes at most), so that a drag begins from a picture as an artist's does.
    QtCore.QTimer.singleShot(500, hook_session)
    QtCore.QTimer.singleShot(500, wait_for_picture)


def wait_for_picture():
    pictures = result['pictures']
    if (pictures and now() - pictures[0][0] >= REST) or now() > 120:
        result['first_picture_at'] = pictures[0][0] if pictures else None
        drag()
        return
    QtCore.QTimer.singleShot(250, wait_for_picture)


def hook_session():
    session = getattr(panel_widget().renderer, 'session', None)
    if session is None or held.get('hooked'):
        if not held.get('hooked'):
            QtCore.QTimer.singleShot(250, hook_session)
        return
    held['hooked'] = True
    session.memory_image.connect(lambda packet: result['pictures'].append([now(), packet[0] if isinstance(packet, (list, tuple)) else None]))
    words = ('Rhea', 'realtime by', 'APPLIED', 'CANCELED', 'DONE', 'FALLBACK', 'exception', 'XPU2 preview session', 'frames by XPU2',
             '@@MODO_WORKERS', 'out of the memory')

    def heard(text):
        for line in str(text).splitlines():
            if any(w in line for w in words):
                result['session'].append([now(), line.strip()[:240]])
            elif line.strip() and 'cannot open texture' not in line:
                result.setdefault('session_other', []).append([now(), line.strip()[:200]])
    session.output.connect(heard)
    # The kit's sends: each dispatch (a request to the session), and each delta made again on a thread (_Rediff).
    dispatch = session._dispatch

    def timed_dispatch(*a, **k):
        started = time.perf_counter()
        sent_before = session.sent
        try:
            return dispatch(*a, **k)
        finally:
            result.setdefault('dispatches', []).append([now(), round(1000 * (time.perf_counter() - started), 2),
                                                        session.sent is not None and session.sent is not sent_before,
                                                        getattr(getattr(session, '_rediff', None), 'isRunning', lambda: False)()])
    session._dispatch = timed_dispatch
    result['session_hooked_at'] = now()


def drag():
    try:
        result['phases']['drag_began'] = now()
        from moonray_modo import interaction
        interaction.dragging = lambda: True
        lx.eval('select.item {%s} set' % held['camera'])
        held['here'] = lx.eval('transform.channel pos.X ?')
        held['offset'] = 0.0
        held['profile'] = cProfile.Profile()

        def move():
            started = time.perf_counter()
            held['offset'] += STEP
            lx.eval('transform.channel pos.X %s' % (held['here'] + held['offset']))
            result['moves'].append([now(), round(1000 * (time.perf_counter() - started), 2)])
        held['mover'] = QtCore.QTimer()
        held['mover'].setInterval(30)
        held['mover'].timeout.connect(move)
        held['mover'].start()
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    save()
    QtCore.QTimer.singleShot(int(1000 * SPAN), release)


def release():
    try:
        if held['mover'] is not None:
            held['mover'].stop()
        from moonray_modo import interaction
        interaction.dragging = lambda: False
        result['phases']['released'] = now()
        if held['profile'] is not None:
            text = io.StringIO()
            pstats.Stats(held['profile'], stream=text).sort_stats('cumulative').print_stats(40)
            (out / 'tick_profile.txt').write_text(text.getvalue())
            held['profile'] = None
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    save()
    QtCore.QTimer.singleShot(int(1000 * RELEASE), finish)


def finish():
    try:
        panel = panel_widget()
        result['frames_shown'] = getattr(panel.renderer, 'frames_shown', None)
        result['status'] = panel.status.text() if hasattr(panel, 'status') and hasattr(panel.status, 'text') else None
        panel.stop()
        store = panel.preferences.store
        for key, value in held['kept'].items():
            if value is None:
                store.remove(key)
            else:
                store.setValue(key, value)
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    result['ended'] = now()
    save()
    lx.eval('!app.quit')


try:
    if os.environ.get('MOONRAY_PROBE_SCENE'):
        lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
