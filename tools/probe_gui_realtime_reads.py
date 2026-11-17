# python
"""GUI: a scene switched to realtime, and every reading of Modo's scene it makes (host.snapshot): when, how long, with
what (evaluated, kept geometry, materials) and from where (the call's last frames). PROBE_SCENE the .lxo (the
Lamborghini unless named), PROBE_ENGINE the preview engine (moonray, which is XPU2's realtime where XPU2 is chosen, or
moonlightipr). RT is pressed once the scene is open; the time to its first picture is noted, the picture saved
(<engine>-realtime.png), and the readings that follow for PROBE_AFTER seconds (15) noted too; then RT off and Modo
quits. Writes test-results/realtime-reads/<engine>.json (PROBE_OUT for another folder), with the MoonRay Terminal's
statuses in the same span."""
import json
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\realtime-reads'))
out.mkdir(parents=True, exist_ok=True)
engine = os.environ.get('PROBE_ENGINE', 'moonray')
scene = os.environ.get('PROBE_SCENE', r'C:\Users\Raphael Tobar\Downloads\Lamborghini(1)\Lamborghini_Moonray.lxo')
after = float(os.environ.get('PROBE_AFTER', '15'))
result = {'scene': scene, 'engine': engine, 'reads': []}
held = {'began': time.monotonic(), 'wall': time.time()}


def save():
    try:
        from moonray_modo import terminal
        result['terminal'] = ['%7.2f %s %s: %s' % (when - held['wall'], kind, source, text[:220])
                              for _, when, kind, source, text in terminal.entries()
                              if kind in ('status', 'command', 'end', 'fail', 'stop', 'note') or 'read' in text.lower()][-200:]
    except Exception:
        result['terminal_error'] = traceback.format_exc()[-500:]
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


def counted(original):
    def snapshot(*args, **kwargs):
        began = time.monotonic()
        try:
            return original(*args, **kwargs)
        finally:
            shown = {k: (v if isinstance(v, (bool, int, float, str, type(None))) else type(v).__name__) for k, v in kwargs.items()}
            result['reads'].append({'at': round(began - held['began'], 2), 'seconds': round(time.monotonic() - began, 2),
                                    'arguments': shown, 'rt_on_at': held.get('rt'),
                                    'from': [line.strip() for line in traceback.format_stack(limit=9)[:-1]][-6:]})
    return snapshot


def image_key(panel):
    image = panel.preview.image
    return None if image.isNull() else image.cacheKey()


def render_first():
    """PROBE_FIRST=render: a preview rendered as it is without realtime first (Start), its picture saved
    (<engine>-render.png) after PROBE_RENDER_SECONDS (20), then stopped, before realtime is switched on."""
    from moonray_modo.panel import Panel
    panel = held['panel'] = next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(engine))
    held['picture'] = image_key(panel)
    held['render_clock'] = time.monotonic()
    panel.start.click()
    later(250, wait_render)


def wait_render(tries=[0]):
    panel = held['panel']
    tries[0] += 1
    if image_key(panel) in (None, held['picture']) and tries[0] < 2400:
        later(250, wait_render)
        return
    result['render_first_picture_seconds'] = round(time.monotonic() - held['render_clock'], 2)
    later(int(float(os.environ.get('PROBE_RENDER_SECONDS', '20')) * 1000), stop_render)


def stop_render():
    panel = held['panel']
    panel.preview.image.save(str(out / ('%s-render.png' % engine)))
    if panel._rendering:
        panel.start.click()
    later(500, wait_stopped)


def wait_stopped(tries=[0]):
    panel = held['panel']
    tries[0] += 1
    if (panel._rendering or getattr(panel, '_stopping', False) or not panel.start.isEnabled()) and tries[0] < 240:
        later(250, wait_stopped)
        return
    result['render_stopped_status'] = panel.status.text()
    later(2000, switch_on)


def switch_on():
    from moonray_modo.panel import Panel
    panel = held['panel'] = next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(engine))
    result['reads_before_rt'] = len(result['reads'])
    held['picture'] = image_key(panel)
    held['rt'] = round(time.monotonic() - held['began'], 2)
    held['rt_clock'] = time.monotonic()
    panel.rt.click()
    result['rt_checked'] = panel.rt.isChecked()
    later(250, wait_picture)


def wait_picture(tries=[0]):
    panel = held['panel']
    tries[0] += 1
    if image_key(panel) in (None, held['picture']) and tries[0] < 1200:
        later(250, wait_picture)
        return
    result['first_picture_seconds'] = round(time.monotonic() - held['rt_clock'], 2)
    result['status_at_picture'] = panel.status.text()
    later(int(after * 1000), finish)


def finish():
    panel = held['panel']
    panel.preview.image.save(str(out / ('%s-realtime.png' % engine)))
    result['status_at_end'] = panel.status.text()
    result['reads_after_rt'] = len(result['reads']) - result.get('reads_before_rt', 0)
    if panel.rt.isChecked():
        panel.rt.click()
    result['done'] = True
    save()
    # Modo let quit, not killed: a test Modo killed asks at its next start about the work it lost.
    QtCore.QTimer.singleShot(4000, lambda: lx.eval('!app.quit'))


try:
    from moonray_modo import host
    host.snapshot = counted(host.snapshot)
    lx.eval('scene.open {%s} normal' % scene)
    result['opened_at'] = round(time.monotonic() - held['began'], 2)
    lx.eval('moonray.page preview')
    later(8000, render_first if os.environ.get('PROBE_FIRST') == 'render' else switch_on)
except Exception:
    result['errors'] = [traceback.format_exc()]
    result['done'] = True
save()
