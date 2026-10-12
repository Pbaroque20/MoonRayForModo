# python
"""Isolated GUI test: an output render stopped part way under Safe Denoising is kept.

Two balls are rendered to an EXR as Render EXR does, with a denoiser and Safe Denoising on. Part way through, Stop is
pressed. What the window then says, and what files there are (the EXR, its denoised copy, their sizes), is written down."""
import json
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/output-stop'
out.mkdir(parents=True, exist_ok=True)
for old in out.glob('frame*'):
    # What is kept beside an output for its denoiser is a folder.
    if old.is_dir():
        import shutil
        shutil.rmtree(str(old))
    else:
        old.unlink()
target = out / 'frame.exr'
result = {}
held = {}
WAIT = int(os.environ.get('MOONRAY_PROBE_LIMIT', '20'))


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def begin():
    try:
        panel = panel_widget()
        panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-0351-tiles')))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        QtWidgets.QApplication.processEvents()
        held['began'] = time.time()
        panel._submit(panel._capture_output(), str(target))
        result['started'] = {'rendering': panel._rendering, 'output_busy': panel._output_busy(), 'status': panel.status.text()}
    except Exception:
        result['begin_error'] = traceback.format_exc()
        save()
        lx.eval('!app.quit')
        return
    save()
    QtCore.QTimer.singleShot(WAIT * 1000, stop)


def stop():
    try:
        panel = panel_widget()
        result['before_stop'] = {'rendering': panel._rendering, 'status': panel.status.text(), 'timing': panel.render_timing.text(), 'button': panel.start.text(),
                                 'safe_files': len(getattr(panel.renderer, 'safe_files', None) or []), 'loaded': bool(getattr(panel.renderer, 'using_session', False))}
        held['stop_at'] = time.time()
        panel.start.click()
        result['at_stop'] = panel.status.text()
    except Exception:
        result['stop_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(200, watch)


def watch():
    panel = panel_widget()
    waited = time.time() - held['stop_at']
    if panel._rendering and waited < 90:
        QtCore.QTimer.singleShot(200, watch)
        return
    result['stop_took'] = round(waited, 1)
    QtCore.QTimer.singleShot(30000, after)


def after():
    try:
        panel = panel_widget()
        result['after'] = {'status': panel.status.text(), 'button': panel.start.text(), 'rendering': panel._rendering, 'buffer': panel.buffer.currentData(),
                           'info': panel.image_info.text(), 'timing': panel.render_timing.text(), 'picture': not panel.preview.image.isNull()}
        result['files'] = {p.name: p.stat().st_size for p in sorted(out.glob('frame*'))}
        log = str(getattr(panel.renderer, 'log', ''))
        result['log'] = [line[:170] for line in log.splitlines() if 'Rendering [' not in line and not line.startswith('@@')][-14:]
        panel.window().grab().save(str(out / 'window.png'))
    except Exception:
        result['after_error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')


try:
    for x in (-.6, .6):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.sphere on')
        lx.eval('tool.attr prim.sphere cenX %s' % x)
        lx.eval('tool.apply')
        lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.render.samples 60')
    lx.eval('moonray.render.denoiser 2')
    lx.eval('moonray.render.denoise_preview 1')
    lx.eval('moonray.render.denoise_safe 1')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
