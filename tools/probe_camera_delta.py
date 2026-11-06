# python
"""Isolated GUI test (tools/launch_gui_probe.py, a test profile): what MoonRay's realtime preview sends its persistent
session when only the camera moves. The scene in MOONRAY_PROBE_SCENE is followed by MoonRay with IPR on (XPU2 where
MOONRAY_PROBE_XPU2=1 and the kit has it); the render camera is turned five times by command; each time every command
sent to the session (delta or full) is written down, and for a full one why the delta was refused (a base the session
had not applied, a different count of lines, or the first line that differs), with the session's own XPU2 lines, into
MOONRAY_PROBE_OUT/report.json."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(os.environ['MOONRAY_PROBE_OUT'])
out.mkdir(parents=True, exist_ok=True)
result = {'moves': [], 'session_lines': []}
held = {'sends': [], 'at': 0.0}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def why(previous, current):
    """Why a delta between two scene texts was refused: their line counts, else the first lines that differ."""
    before, after = previous.splitlines(), current.splitlines()
    if len(before) != len(after):
        changed = [(i, a[:160], b[:160]) for i, (a, b) in enumerate(zip(before, after)) if a != b][:3]
        return {'lines': [len(before), len(after)], 'first_changes': changed}
    changed = [(i, a[:160], b[:160]) for i, (a, b) in enumerate(zip(before, after)) if a != b]
    return {'same_lines': len(after), 'changes': len(changed), 'first_changes': changed[:6]}


def watch(session):
    original = session._dispatch

    def dispatch(*a, **k):
        request, applied = session.latest, session.applied
        prepared = (request or {}).get('prepared') if request else None
        record = {'at': round(time.perf_counter() - held['at'], 3), 'id': (request or {}).get('id')}
        if request and not (applied and request['id'] == applied['id']):
            if prepared is not None and prepared['base'] is not applied:
                record['mode'] = 'full'
                record['reason'] = 'stale base (prepared against %s, applied %s)' % ((prepared['base'] or {}).get('id'), (applied or {}).get('id'))
            else:
                delta = prepared['delta'] if prepared is not None else None
                record['mode'] = 'delta' if (delta is not None and applied) else 'full'
                if record['mode'] == 'full':
                    record['reason'] = why(applied['text'], request['text']) if applied else 'nothing applied yet'
                else:
                    record['delta_objects'] = [line[:120] for line in delta.splitlines() if line.endswith('{')][:10]
        held['sends'].append(record)
        return original(*a, **k)
    session._dispatch = dispatch
    def lines(text):
        result['session_lines'].extend(line[:200] for line in text.splitlines() if 'XPU2' in line or 'camera' in line.lower())
    session.output.connect(lines)


def begin():
    try:
        panel = panel_widget()
        if os.environ.get('MOONRAY_PROBE_XPU2') == '1':
            panel.preferences.set('xpu2/renderer', 'xpu2')
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        QtWidgets.QApplication.processEvents()
        if not panel.ipr_mode.isChecked():
            panel.ipr_mode.setChecked(True)
        panel.start.click()
        held['camera'] = modo.Scene().renderCamera.id
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(int(os.environ.get('MOONRAY_PROBE_SETTLE', '60')) * 1000, lambda: move(0))


def move(count):
    try:
        session = panel_widget().renderer.session
        if not getattr(session, '_probe_watched', False):
            watch(session)
            session._probe_watched = True
        held['sends'] = []
        lx.eval('select.item {%s} set' % held['camera'])
        held['at'] = time.perf_counter()
        # Sideways: a camera aimed at a target keeps its turn whatever its rotation channel says.
        lx.eval('transform.channel pos.X %s' % (0.05 * (count + 1)))
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    QtCore.QTimer.singleShot(5000, lambda: moved(count))


def moved(count):
    result['moves'].append({'sends': list(held['sends'])})
    save()
    if count < 4:
        move(count + 1)
    else:
        finish()


def finish():
    try:
        panel_widget().stop()
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
