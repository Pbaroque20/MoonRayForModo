# python
"""Isolated GUI test: render a cube with MoonRay from the runtime named in MOONRAY_PROBE_RUNTIME and write down what
the window says and everything MoonRay printed. For finding out why a runtime will not render."""
import json
import os
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/render-log'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def begin():
    try:
        panel = panel_widget()
        held['stored'] = [panel.preferences.store.value(key, None) for key in ('runtime', 'preview_engine', 'ipr')]
        panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-0350-pool')))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        QtWidgets.QApplication.processEvents()
        # How often MoonRay tells of the tiles its workers are on, and how evenly.
        import time
        held['told'] = []
        held['count'] = lambda packet: held['told'].append(time.monotonic()) if packet else None
        panel.renderer.workers.connect(held['count'])
        if not panel._rendering:
            panel.start.click()
    except Exception:
        result['error'] = traceback.format_exc()
    QtCore.QTimer.singleShot(int(os.environ.get('MOONRAY_PROBE_WAIT', '20')) * 1000, finish)


def finish():
    try:
        panel = panel_widget()
        result.update(status=panel.status.text(), tooltip=panel.status.toolTip(), timing=panel.render_timing.text(), picture=not panel.preview.image.isNull(),
                      loaded=bool(getattr(panel.renderer, 'using_session', False)))
        told = held.get('told', [])
        gaps = sorted(b - a for a, b in zip(told, told[1:]))
        if gaps:
            result['tiles_told'] = {'times': len(told), 'a_second': round(len(gaps) / max(told[-1] - told[0], 1e-6), 1), 'usual_gap_ms': round(1000 * gaps[len(gaps) // 2]),
                                    'longest_gap_ms': round(1000 * gaps[-1]), 'gaps_over_150ms': sum(1 for gap in gaps if gap > .15)}
        result['outlines_on_screen'] = len(panel.preview._fading)
        (out / 'moonray.txt').write_text('\n'.join(line for line in str(panel.renderer.log).splitlines() if 'Rendering [' not in line and not line.startswith('@@')),
                                         encoding='utf-8', errors='replace')
        panel.window().grab().save(str(out / 'window.png'))
        if panel._rendering or panel._following:
            panel.stop()
        for key, value in zip(('runtime', 'preview_engine', 'ipr'), held['stored']):
            if value is None:
                panel.preferences.store.remove(key)
            else:
                panel.preferences.store.setValue(key, value)
    except Exception:
        result['finish_error'] = traceback.format_exc()
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
    lx.eval('!app.quit')


try:
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
QtCore.QTimer.singleShot(8000, begin)
