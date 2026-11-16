# python
"""GUI: a scene's preview on one engine, as the artist sees it. PROBE_SCENE (the dragon test scene unless named) is
opened, the preview set to PROBE_ENGINE (moonlightipr, moonray or moonray_ls; moonlightipr unless named), Start pressed,
and after PROBE_SECONDS (20) the picture saved with the status line and the notices: PROBE_OUT/<engine>.png and
<engine>.json (test-results/engine-picture). Modo then quits."""
import json
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\engine-picture'))
out.mkdir(parents=True, exist_ok=True)
engine = os.environ.get('PROBE_ENGINE', 'moonlightipr')
scene = os.environ.get('PROBE_SCENE', r'C:\Users\Raphael Tobar\Downloads\dragon_test.lxo')
seconds = float(os.environ.get('PROBE_SECONDS', '20'))
result = {'scene': scene, 'engine': engine}
held = {}


def save():
    (out / ('%s.json' % engine)).write_text(json.dumps(result, indent=1, default=str))


def later(ms, step):
    def run():
        try:
            step()
        except Exception:
            result.setdefault('errors', []).append(step.__name__ + ': ' + traceback.format_exc())
            result['done'] = True
            save()
            QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))
    QtCore.QTimer.singleShot(ms, run)


def start():
    from moonray_modo.panel import Panel
    panel = held['panel'] = next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(engine))
    panel.start.click()
    held['began'] = time.monotonic()
    later(int(seconds * 1000), grab)


def grab():
    panel = held['panel']
    panel.preview.image.save(str(out / ('%s.png' % engine)))
    result.update(status=panel.status.text(), seconds=round(time.monotonic() - held['began'], 1))
    for name in ('notices', 'notice'):
        widget = getattr(panel, name, None)
        if widget is not None and hasattr(widget, 'text'):
            result['notices'] = widget.text()
    if panel._rendering:
        panel.start.click()   # Stop
    result['done'] = True
    save()
    # Modo let quit, not killed: a test Modo killed asks at its next start about the work it lost.
    QtCore.QTimer.singleShot(4000, lambda: lx.eval('!app.quit'))


try:
    lx.eval('scene.open {%s} normal' % scene)
    lx.eval('moonray.page preview')
    later(5000, start)
except Exception:
    result['errors'] = [traceback.format_exc()]
    result['done'] = True
save()
