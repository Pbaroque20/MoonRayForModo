# python
"""GUI: a MoonLightIPR render to files is premultiplied, as MoonRay's are. A new scene, a cube in front of Modo's default
environment (seen by the camera), rendered by Render Animation with MoonLightIPR as the engine: one frame at 32 samples,
an EXR and a PNG beside it. The EXR should hold R, G, B, A and the Environment background's channels, its colour 0 where
its alpha is 0 (the sky taken out, kept as its own channels). The files are read afterwards (tools/check_alpha_edges.py
reads such files the same way). Writes test-results/moonlightipr-premultiplied/report.json; Modo then quits."""
import json
import pathlib
import shutil
import time
import traceback
import lx
from PySide2 import QtCore

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\moonlightipr-premultiplied')
shutil.rmtree(str(out), ignore_errors=True)
out.mkdir(parents=True, exist_ok=True)
result = {}
state = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel():
    # The kit's own list: QApplication.allWidgets() wraps Modo's widgets, which then crash Modo as it quits.
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def begin():
    try:
        p = panel()
        p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonlightipr'))
        from moonray_modo.playblast import MoonLightIPRAnimation
        import modo
        widest = int(modo.Scene().renderItem.channel('resX').get())
        sequence = MoonLightIPRAnimation(p, str(out / 'frames'), 1, 1, 24.0, prefix='frame', width=widest, samples=32,
                                         digits=4, export_as={'type': 'png8', 'quality': 92, 'only': False})
        if p.ipr_mode.isChecked():
            p.ipr_mode.setChecked(False)
        p.stop()
        p.sequence = sequence
        state['began'] = time.monotonic()
        sequence.start()
        QtCore.QTimer.singleShot(1000, wait_animation)
    except Exception:
        result['animation_error'] = traceback.format_exc()
        finish()


def wait_animation():
    try:
        p = panel()
        if p.sequence is not None and p.sequence.running and time.monotonic() - state['began'] < 300:
            QtCore.QTimer.singleShot(500, wait_animation)
            return
        sequence = p.sequence
        result['animation'] = {'seconds': round(time.monotonic() - state['began'], 1), 'status': p.status.text(),
                               'alpha_came': bool(getattr(sequence, 'alpha', None)), 'sky_came': bool(getattr(sequence, 'sky', None)),
                               'files': sorted((f.name, f.stat().st_size) for f in (out / 'frames').glob('*'))}
    except Exception:
        result['animation_error'] = traceback.format_exc()
    finish()


def finish():
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


try:
    lx.eval('scene.new')
    lx.eval('item.create mesh {Probe Cube}')
    import modo
    cube = next(i for i in modo.Scene().items('mesh') if i.name == 'Probe Cube')
    lx.eval('select.item {%s} set' % cube.id)
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('select.drop item')
    for name, value in (('resX', 480), ('resY', 270)):
        modo.Scene().renderItem.channel(name).set(value)
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
