# python
"""GUI: a scene in realtime with the camera moved, and a Render after, as an artist does: PROBE_SCENE (the Lamborghini
unless named) opened, its popups answered (an unknown Octane item: Yes to All; ACES: No; each noted), the preview on
PROBE_ENGINE (moonray: XPU2's realtime where XPU2 is chosen; or moonlightipr); RT on, and once its first picture is in, the
render camera moved PROBE_MOVES times (0.3 m along X each), each time how long until the picture shows it (the preview's
picture changing); then RT off, and with PROBE_RENDER=1 (the default) Start pressed for a render and how long until it is
done. Writes test-results/realtime-camera/<engine>.json (PROBE_OUT for another folder) with the MoonRay Terminal's lines
(what the renderer printed) and the pictures; Modo then quits."""
import json
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\realtime-camera'))
out.mkdir(parents=True, exist_ok=True)
engine = os.environ.get('PROBE_ENGINE', 'moonray')
scene = os.environ.get('PROBE_SCENE', r'C:\Users\Raphael Tobar\Downloads\Lamborghini(1)\Lamborghini_Moonray.lxo')
moves = int(os.environ.get('PROBE_MOVES', '3'))
result = {'scene': scene, 'engine': engine, 'dialogs': [], 'moves': [], 'reads': []}
held = {'began': time.monotonic(), 'wall': time.time()}


def stamp():
    return round(time.monotonic() - held['began'], 2)


def save():
    try:
        from moonray_modo import terminal
        result['terminal'] = ['%7.2f %s %s: %s' % (when - held['wall'], kind, source, text[:260])
                              for _, when, kind, source, text in terminal.entries()
                              if not text.startswith(('@@MODO_TILES', '@@MODO_WORKERS', '@@MODO_GPU_WORKERS', '@@MODO_PROGRESS'))][-600:]
    except Exception:
        result['terminal_error'] = traceback.format_exc()[-500:]
    (out / ('%s.json' % engine)).write_text(json.dumps(result, indent=1, default=str))


# Modo's popups as the scene opens (modal: their own event loop runs this timer): an unknown Octane item, Yes to All; ACES,
# No. Any other popup is noted and left for the timeout.
ANSWERS = (('octane', ('Yes to All', 'Yes To All', 'Yes to all', 'Yes')), ('aces', ('No',)))


def answer_popups():
    result['popup_ticks'] = result.get('popup_ticks', 0) + 1
    try:
        main = held.get('main')
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if not widget.isVisible() or widget is main:
                continue
            # Any window of Modo's that is not its main one (its popups need not be QDialogs): its words and buttons.
            words = ' '.join(label.text() for label in widget.findChildren(QtWidgets.QLabel)) + ' ' + widget.windowTitle()
            buttons = {button.text().replace('&', ''): button for button in widget.findChildren(QtWidgets.QAbstractButton) if button.isVisible()}
            if not buttons:
                continue
            for topic, wanted in ANSWERS:
                if topic in words.lower():
                    for label in wanted:
                        if label in buttons:
                            result['dialogs'].append({'at': stamp(), 'kind': type(widget).__name__, 'text': words[:300], 'pressed': label})
                            buttons[label].click()
                            save()
                            return
            key = type(widget).__name__ + ':' + words[:120]
            if key not in held.setdefault('noted', set()):
                held['noted'].add(key)
                result['dialogs'].append({'at': stamp(), 'kind': type(widget).__name__, 'text': words[:300], 'buttons': list(buttons),
                                          'pressed': None})
                save()
    except Exception:
        result.setdefault('popup_errors', []).append(traceback.format_exc()[-400:])
        save()


held['main'] = next((w for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, QtWidgets.QMainWindow) and w.isVisible()), None)
popups = QtCore.QTimer()
popups.timeout.connect(answer_popups)
popups.start(300)
save()


def later(ms, step):
    def run():
        try:
            step()
        except Exception:
            result.setdefault('errors', []).append(step.__name__ + ': ' + traceback.format_exc())
            finish()
    QtCore.QTimer.singleShot(ms, run)


def panel():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def picture_key():
    image = panel().preview.image
    return None if image.isNull() else image.cacheKey()


def wait_change(name, then, limit):
    """Until the picture changes from the one held, or limit seconds: the time it took noted under name."""
    began = time.monotonic()

    def look():
        if picture_key() not in (None, held['picture']):
            result[name] = round(time.monotonic() - began, 2)
            save()
            then()
            return
        if time.monotonic() - began > limit:
            result[name] = 'no new picture in %d s' % limit
            result.setdefault('stalls', []).append({'at': stamp(), 'step': name, 'status': panel().status.text()})
            save()
            then()
            return
        later(200, look)
    later(200, look)


# PROBE_ENGINES: realtime on each in turn (moonray moonlightipr moonray: the engine switched between them, as an artist
# compares them), the camera moved in each; then the render on the last. PROBE_ENGINE alone: that engine.
phases = os.environ.get('PROBE_ENGINES', engine).split()
result['phases'] = []


def switch_on():
    p = panel()
    name = phases[len(result['phases'])]
    result['phases'].append({'engine': name, 'at': stamp()})
    p.preview_engine.setCurrentIndex(p.preview_engine.findData(name))
    held['picture'] = picture_key()
    result['rt_on_at'] = stamp()
    p.rt.click()
    result['rt_checked'] = p.rt.isChecked()
    result['phases'][-1]['rt_checked'] = p.rt.isChecked()
    result['phases'][-1]['status'] = p.status.text()
    held['moves_from'] = len(result['moves'])
    wait_change('rt_first_picture_seconds', lambda: (result['phases'][-1].update(first=result.get('rt_first_picture_seconds')),
                                                     later(5000, move_camera)), 600)


def move_camera():
    if len(result['moves']) - held.get('moves_from', 0) >= moves:
        later(3000, switch_off)
        return
    import modo
    camera = modo.Scene().renderCamera
    lx.eval('select.item {%s} set' % camera.id)
    if 'x0' not in held:
        try:
            held['x0'] = float(lx.eval1('transform.channel pos.X ?'))
        except Exception:
            held['x0'] = 0.0
    # Each move 0.3 m further along X than the last (the same value set again would change nothing).
    x = held['x0'] + 0.3 * (len(result['moves']) + 1)
    held['picture'] = picture_key()
    entry = {'at': stamp(), 'x': round(x, 3), 'status_before': panel().status.text()}
    result['moves'].append(entry)
    lx.eval('transform.channel pos.X %s' % x)
    began = time.monotonic()

    def look(tries=[0]):
        if picture_key() not in (None, held['picture']):
            entry['picture_seconds'] = round(time.monotonic() - began, 2)
            entry['status_after'] = panel().status.text()
            save()
            later(4000, move_camera)
            return
        if time.monotonic() - began > 90:
            entry['picture_seconds'] = 'no new picture in 90 s'
            entry['status_after'] = panel().status.text()
            result.setdefault('stalls', []).append({'at': stamp(), 'step': 'camera move %d' % len(result['moves']),
                                                    'status': panel().status.text()})
            save()
            later(1000, move_camera)
            return
        later(200, look)
    later(200, look)


def switch_off():
    p = panel()
    name = result['phases'][-1]['engine']
    p.preview.image.save(str(out / ('%s-%d-%s-realtime.png' % (engine, len(result['phases']), name))))
    if p.rt.isChecked():
        p.rt.click()
    result['rt_off_at'] = stamp()
    result['phases'][-1]['off_at'] = stamp()
    save()
    if len(result['phases']) < len(phases):
        later(8000, switch_on)
        return
    if os.environ.get('PROBE_RENDER', '1') != '1':
        finish()
        return
    later(6000, render)


def render():
    p = panel()
    held['picture'] = picture_key()
    result['render_at'] = stamp()
    p.start.click()
    began = time.monotonic()

    def look():
        p = panel()
        status = p.status.text()
        if not p._rendering and time.monotonic() - began > 5:
            result['render_seconds'] = round(time.monotonic() - began, 2)
            result['render_status'] = status
            p.preview.image.save(str(out / ('%s-render.png' % engine)))
            finish()
            return
        if time.monotonic() - began > float(os.environ.get('PROBE_RENDER_LIMIT', '240')):
            result['render_seconds'] = 'still rendering after %s s' % os.environ.get('PROBE_RENDER_LIMIT', '240')
            result['render_status'] = status
            result.setdefault('stalls', []).append({'at': stamp(), 'step': 'render', 'status': status})
            p.preview.image.save(str(out / ('%s-render.png' % engine)))
            if p._rendering:
                p.start.click()   # Stop
            later(20000, finish)
            return
        later(500, look)
    later(500, look)


def finish():
    popups.stop()
    result['done'] = True
    save()
    # Modo let quit, not killed: a test Modo killed asks at its next start about the work it lost.
    QtCore.QTimer.singleShot(4000, lambda: lx.eval('!app.quit'))


try:
    from moonray_modo import host

    def counted(original):
        def snapshot(*args, **kwargs):
            began = time.monotonic()
            try:
                return original(*args, **kwargs)
            finally:
                result['reads'].append({'at': round(began - held['began'], 2), 'seconds': round(time.monotonic() - began, 2),
                                        'arguments': {k: (v if isinstance(v, (bool, int, float, str, type(None))) else type(v).__name__)
                                                      for k, v in kwargs.items()}})
        return snapshot
    host.snapshot = counted(host.snapshot)
    # Modo's popups as a scene opens hold its Python still (the timer above never ticks under them): PROBE_DIALOGS=0 (the
    # default) opens the scene with them suppressed (!scene.open, their default answers), as the command-line probes do.
    lx.eval(('scene.open {%s} normal' if os.environ.get('PROBE_DIALOGS') == '1' else '!scene.open {%s} normal') % scene)
    result['opened_at'] = stamp()
    lx.eval('moonray.page preview')
    later(8000, switch_on)
except Exception:
    result['errors'] = [traceback.format_exc()]
    finish()
save()
