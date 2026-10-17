# python
"""Isolated GUI test: each status the preview window shows is a line of the MoonRay Terminal.

A ball is rendered with MoonRay from the preview window while the Terminal is open; the two lines are read while it
renders and once it has finished, with the Terminal's status lines, and the Terminal saved as a picture each time."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/terminal-status'
out.mkdir(parents=True, exist_ok=True)
runtime = pathlib.Path.home() / 'AppData/Roaming/Luxology/Kits/MoonRayForModo/runtime'
result = {'reads': []}


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def read(name):
    from moonray_modo import terminal
    window = terminal._window
    window.refresh()
    result['reads'].append({'when': name, 'preview': panel_widget().status.text(), 'prompt': window.prompt.text(),
                            'status_lines': [text for _, _, kind, source, text in terminal.entries() if kind == 'status'],
                            'running': [(source, ident in terminal._resident) for ident, (source, began) in terminal._running.items()]})
    window.grab().save(str(out / (name + '.png')))
    (out / 'report.json').write_text(json.dumps(result, indent=1))


def run(steps, index=0):
    if index >= len(steps):
        lx.eval('!app.quit')
        return
    function, wait = steps[index]
    try:
        function()
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
        (out / 'report.json').write_text(json.dumps(result, indent=1))
    QtCore.QTimer.singleShot(wait, lambda: run(steps, index + 1))


def start():
    panel = panel_widget()
    panel.preferences.set('runtime', str(runtime))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    lx.eval('moonray.terminal')
    read('before')
    panel.start.click()


try:
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.render.samples 3')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
QtCore.QTimer.singleShot(8000, lambda: run([(start, 2500), (lambda: read('rendering'), 60000), (lambda: read('finished'), 500)]))
