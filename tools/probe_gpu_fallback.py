# python
"""Isolated GUI test: a GPU failure in the preview's MoonRay session is rendered again on the CPU.

A sphere is rendered in the preview with MoonRay in Auto (the GPU first). Part way, the session's GPU error is marked
as MoonRay's log would mark it, and its process is ended, as when MoonRay's GPU tracing fails. Noted after waiting:
the status, the notices, the backend the render went to, and whether the CPU fallback is held."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/gpu-fallback'
out.mkdir(parents=True, exist_ok=True)
runtime = pathlib.Path.home() / 'AppData/Roaming/Luxology/Kits/MoonRayForModo/runtime'
result = {'steps': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def start():
    panel = panel_widget()
    held['runtime'] = panel.preferences.store.value('runtime')
    panel.preferences.set('runtime', str(runtime))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    panel.start.click()
    result['steps'].append('started')


def fail():
    renderer = panel_widget().renderer
    result['before'] = {'status': panel_widget().status.text(), 'session_running': renderer.session.running()}
    renderer.gpu_error = True
    renderer.session.process.kill()
    result['steps'].append('session killed with the GPU error marked')


def after():
    panel = panel_widget()
    renderer = panel.renderer
    result['after'] = {'status': panel.status.text(), 'notices': panel.warnings.toPlainText()[:500], 'backend': renderer.backend_status,
                       'cpu_fallback': renderer.cpu_fallback, 'session_running': renderer.session.running(),
                       'mode_asked': (renderer.active or {}).get('snapshot', {}).get('execution_mode')}
    panel.window().grab().save(str(out / 'after.png'))
    if held.get('runtime') is None:
        panel.preferences.store.remove('runtime')
    else:
        panel.preferences.store.setValue('runtime', held['runtime'])


def run(steps, index=0):
    if index >= len(steps):
        save()
        lx.eval('!app.quit')
        return
    function, wait = steps[index]
    try:
        function()
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    save()
    QtCore.QTimer.singleShot(wait, lambda: run(steps, index + 1))


try:
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.render.samples 64')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(6000, lambda: run([(start, 6000), (fail, 30000), (after, 500)]))
