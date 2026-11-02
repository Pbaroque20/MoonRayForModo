# python
"""Isolated GUI test: how long a MoonLightIPR Playblast's frames take. The same four frames of a moving ball, flat out as a playblast
is, and then paced as a preview is (the flag taken off before each frame is handed over). Writes test-results/playblast-speed/report.json."""
import json
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/playblast-speed'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}
SAMPLES = 256


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def blast(name, paced, then):
    from moonray_modo.playblast import Playblast
    panel = panel_widget()
    panel.stop()
    begun = time.perf_counter()
    run = Playblast(panel, str(out / name), 1, 4, 24.0, prefix='probe', width=320, samples=SAMPLES)
    held[name] = run
    if paced:
        capture = run.capture
        submit = panel._submit

        def plain(snapshot):
            snapshot.pop('_flat_out', None)
            return submit(snapshot)
        panel._submit = plain
        held['restore'] = lambda: setattr(panel, '_submit', submit)

    def finished(files):
        result[name] = {'frames': len(files), 'seconds': round(time.perf_counter() - begun, 2),
                        'seconds a frame': round((time.perf_counter() - begun) / max(1, len(files)), 2), 'status': panel.status.text()[:90]}
        save()
        if paced:
            held['restore']()
        QtCore.QTimer.singleShot(500, then)
    run.done.connect(finished)
    panel.sequence = run
    run.start()


def paced_run():
    blast('paced', True, lambda: lx.eval('!app.quit'))


def begin():
    try:
        blast('flat', False, paced_run)
    except Exception:
        result['error'] = traceback.format_exc()
        save()
        lx.eval('!app.quit')


try:
    import modo
    lx.eval('select.typeFrom item')
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    ball = modo.Scene().selectedByType('mesh')[0]
    ball.position.x.set(-1.0, time=1 / 24.0, key=True)
    ball.position.x.set(1.0, time=4 / 24.0, key=True)
    lx.eval('select.time 0')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
