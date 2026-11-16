# python
"""Isolated GUI test: a preview stopped by hand keeps MoonRay XPU2 loaded and idle (render.Renderer.stop keep,
persistent.Session.pause), the next Start renders at once from the process kept, and the scene's closing lets the
process go (Panel._scene_closed, Session.release: told to quit, killed only past its grace).

MOONRAY_PROBE_SCENE (the dragon test scene unless named) is opened and rendered with XPU2; Stop is pressed once a
picture is in; the process's id and whether it runs are noted; Start is pressed again and the time to its first picture
noted; Stop again; then the scene's closing as Modo reports it, and how long the process takes to end.
Writes test-results/idle-engine/report.json."""
import json
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/idle-engine'
out.mkdir(parents=True, exist_ok=True)
scene = os.environ.get('MOONRAY_PROBE_SCENE', r'C:\Users\Raphael Tobar\Downloads\dragon_test.lxo')
result = {'scene': scene, 'steps': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
    # The MoonRay Terminal's lines (what XPU2 printed, the window's statuses), timed from the probe's start, beside the
    # report: where a stop went, step by step. Outline packets left out.
    try:
        from moonray_modo import terminal
        lines = []
        for serial, when, kind, source, text in terminal.entries():
            if text.startswith(('@@MODO_TILES', '@@MODO_WORKERS', '@@MODO_GPU_WORKERS', '@@MODO_PROGRESS')):
                continue
            lines.append('%8.3f %-7s %s: %s' % (when - held.get('wall', when), kind, source, text))
        (out / 'terminal.txt').write_text('\n'.join(lines), encoding='utf-8')
    except Exception:
        result.setdefault('errors', []).append('terminal: ' + traceback.format_exc())


def later(ms, step):
    def run():
        try:
            step()
        except Exception:
            result.setdefault('errors', []).append(step.__name__ + ': ' + traceback.format_exc())
            result['done'] = True
        save()
    QtCore.QTimer.singleShot(ms, run)


def note(what, **more):
    panel = held.get('panel')
    session = panel.renderer.session if panel else None
    entry = {'step': what, 't': round(time.monotonic() - held['began'], 2)}
    if session is not None:
        entry.update(running=session.running(), pid=session.process.processId() if session.running() else None,
                     xpu2=getattr(session, 'xpu2_active', None), status=panel.status.text())
    entry.update(more)
    result['steps'].append(entry)


def image_key():
    image = held['panel'].preview.image
    return None if image.isNull() else image.cacheKey()


def wait_for_picture(after, then, tries=600):
    """Until the preview shows a picture other than the one it showed (after), then then(seconds waited)."""
    began = held.setdefault('waiting_since', time.monotonic())
    if image_key() not in (None, after):
        held.pop('waiting_since', None)
        then(round(time.monotonic() - began, 2))
        return
    if tries <= 0:
        held.pop('waiting_since', None)
        note('no picture in time')
        result['done'] = True
        return
    later(100, lambda: wait_for_picture(after, then, tries - 1))


def start_first():
    from moonray_modo.panel import Panel
    panel = held['panel'] = next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))
    panel.preferences.set('xpu2/renderer', 'xpu2')
    panel.preferences.set('idle_release_minutes', 0)
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    note('before the first start')
    held['before'] = image_key()
    panel.start.click()
    wait_for_picture(held['before'], first_picture)


def first_picture(seconds):
    note('first picture', seconds=seconds)
    later(3000, stop_first)


def stop_first():
    held['pid'] = held['panel'].renderer.session.process.processId()
    held['panel'].preview.image.save(str(out / 'before-stop.png'))
    held['stop_at'] = time.monotonic()
    held['panel'].start.click()   # Stop
    later(200, lambda: wait_stopped(after_stop, 400))


def wait_stopped(then, tries):
    """Until the window has stopped (the button given back, not rendering), then then()."""
    panel = held['panel']
    if (panel._rendering or not panel.start.isEnabled() or getattr(panel, '_stopping', False)) and tries > 0:
        later(100, lambda: wait_stopped(then, tries - 1))
        return
    note('stopped', seconds=round(time.monotonic() - held['stop_at'], 2), rendering=panel._rendering)
    then()


def after_stop():
    session = held['panel'].renderer.session
    held['panel'].preview.image.save(str(out / 'after-stop.png'))
    note('after Stop', kept=session.running() and session.process.processId() == held['pid'])
    held['before'] = image_key()
    held['restart'] = time.monotonic()
    held['panel'].start.click()   # Start again
    wait_for_picture(held['before'], second_picture)


def second_picture(seconds):
    session = held['panel'].renderer.session
    note('first picture after Start again', seconds=seconds,
         same_process=session.running() and session.process.processId() == held['pid'])
    later(2000, stop_second)


def stop_second():
    held['stop_at'] = time.monotonic()
    held['panel'].start.click()   # Stop
    later(200, lambda: wait_stopped(close_scene, 400))


def close_scene():
    note('before the scene closes')
    held['closed_at'] = time.monotonic()
    # As Modo's closing of the scene reaches the window (Panel._poll).
    held['panel']._scene_closed()
    later(200, lambda: wait_gone(150))


def wait_gone(tries):
    session = held['panel'].renderer.session
    if session.running() and tries > 0:
        later(100, lambda: wait_gone(tries - 1))
        return
    note('after the scene closed', ended_after=round(time.monotonic() - held['closed_at'], 2),
         exit_code=session.process.exitCode(), exit_status=int(session.process.exitStatus()))
    result['done'] = True
    save()
    # Modo let quit, not killed: a test Modo killed asks at its next start about the work it lost.
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


try:
    held['began'] = time.monotonic()
    held['wall'] = time.time()
    lx.eval('scene.open {%s} normal' % scene)
    lx.eval('moonray.page preview')
    later(5000, start_first)
except Exception:
    result['errors'] = [traceback.format_exc()]
    result['done'] = True
save()
