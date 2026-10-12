# python
"""Isolated GUI test: a render to a file writes the compositor's picture beside it.

Two balls, a denoiser on, and a compositor graph stored with the scene (the denoised beauty, a stop up, multiplied by
the alpha). The scene is rendered to an EXR as Render EXR does. Afterwards the files beside it are listed."""
import json
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/compositor-output'
out.mkdir(parents=True, exist_ok=True)
target = out / 'frame.exr'
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def begin():
    try:
        panel = panel_widget()
        for old in ('frame.exr', 'frame.denoised.exr', 'frame.composite.exr'):
            if (out / old).is_file():
                (out / old).unlink()
        panel.preferences.set('runtime', str(root / 'runtime/steady-0351-tiles'))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        graph = {'nodes': {'a': {'type': 'input', 'parameters': {'buffer': 'denoised_beauty'}, 'inputs': {}},
                           'm': {'type': 'input', 'parameters': {'buffer': 'alpha'}, 'inputs': {}},
                           'x': {'type': 'grade', 'parameters': {'exposure': 1.0}, 'inputs': {'image': 'a'}},
                           'j': {'type': 'merge', 'parameters': {'mode': 'multiply'}, 'inputs': {'a': 'x', 'b': 'm'}},
                           'out': {'type': 'output', 'parameters': {}, 'inputs': {'image': 'j'}}}, 'root': 'out'}
        result['stored'] = panel._store(compositor=graph)
        QtWidgets.QApplication.processEvents()
        held['began'] = time.time()
        panel._submit(panel._capture_output(), str(target))
        result['started'] = panel._output_busy()
    except Exception:
        result['begin_error'] = traceback.format_exc()
        save()
        lx.eval('!app.quit')
        return
    save()
    QtCore.QTimer.singleShot(1000, watch)


def watch():
    panel = panel_widget()
    if panel._output_busy() and time.time() - held['began'] < 240:
        QtCore.QTimer.singleShot(1000, watch)
        return
    try:
        result['took'] = round(time.time() - held['began'], 1)
        result['status'] = panel.status.text()
        result['files'] = {p.name: p.stat().st_size for p in sorted(out.glob('frame*')) if p.is_file()}
        result['log'] = [line[:150] for line in str(getattr(panel.renderer, 'log', '')).splitlines() if 'omposit' in line][-3:]
    except Exception:
        result['watch_error'] = traceback.format_exc()
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
    lx.eval('moonray.render.samples 3')
    lx.eval('moonray.render.denoiser 2')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
