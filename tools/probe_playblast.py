# python
"""Isolated GUI test: MoonLightIPR Playblast, and realtime waiting out an animation that is playing.

A ball that moves from left to right over four frames.
1. With MoonRay the engine chosen, a playblast of frames 1 to 4 is begun: each frame is rendered by MoonLightIPR at the
   playblast's own width and samples, and saved as a PNG; the ball is further right in each.
2. Its player shows the frames; the dialog is as the menu opens it (moonray.page playblast).
3. MoonLightIPR with realtime on: while the scene's time is stepped as playing does, nothing is rendered; once it
   stops, the frame it stopped on is rendered, once."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/playblast'
frames = out / 'frames'
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}
held = {'submits': [], 'player': None, 'dialog': None, 'tick': None, 'time': 0.0}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def centre(path):
    """Where across the picture the ball is: the middle of what differs from the corner's colour, 0 to 1."""
    image = QtGui.QImage(str(path)).convertToFormat(QtGui.QImage.Format_RGB888)
    if image.isNull():
        return None
    w, h, stride = image.width(), image.height(), image.bytesPerLine()
    data = bytes(image.constBits())
    corner = data[0:3]
    total = count = 0
    for y in range(0, h, 3):
        for x in range(0, w, 3):
            i = y * stride + x * 3
            if abs(data[i] - corner[0]) + abs(data[i + 1] - corner[1]) + abs(data[i + 2] - corner[2]) > 60:
                total += x; count += 1
    return [w, h, round(total / count / w, 3) if count else None]


def note(name, widget=None):
    panel = panel_widget()
    result['steps'].append({'step': name, 'engine': panel.preview_engine.currentText(), 'button': panel.start.text(), 'rendering': panel._rendering,
                            'following': panel._following, 'busy': panel._output_busy(), 'submits': len(held['submits']), 'status': panel.status.text()[:90]})
    (widget or panel).grab().save(str(out / ('%02d_%s.png' % (len(result['steps']), name))))
    save()


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


@step(45000)
def begin():
    from moonray_modo.playblast import Playblast
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / 'runtime/steady-0351-tiles'))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    submit = panel.renderer.submit

    def counted(scene, runtime, width, height, *a, **k):
        held['submits'].append([k.get('engine'), width, height, scene.get('frame'), bool(k.get('output') or (len(a) > 3 and a[3]))])
        return submit(scene, runtime, width, height, *a, **k)
    panel.renderer.submit = counted
    for old in frames.glob('probe.*.png') if frames.is_dir() else ():
        old.unlink()
    blast = Playblast(panel, str(frames), 1, 4, 24.0, prefix='probe', width=320, samples=16)
    blast.done.connect(lambda files: result.update(done=[pathlib.Path(f).name for f in files]))
    panel.stop()
    panel.sequence = blast
    blast.start()
    result['samples_while_running'] = panel.renderer.moonlightipr_samples
    result['busy_while_running'] = panel._output_busy()


@step(2500)
def played():
    from moonray_modo.playblast import Player
    panel = panel_widget()
    note('playblast_done')
    files = sorted(frames.glob('probe.*.png'))
    result['files'] = [f.name for f in files]
    result['centres'] = [centre(f) for f in files]
    result['renders'] = list(held['submits'])
    result['samples_after'] = panel.renderer.moonlightipr_samples
    held['player'] = Player([str(f) for f in files], 24.0, panel)
    held['player'].show()


@step(2500)
def dialog():
    note('player', held['player'])
    result['player_frame'] = held['player'].name.text()
    held['player'].close()

    def shut():
        from moonray_modo.playblast import PlayblastDialog
        found = [w for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, PlayblastDialog) and w.isVisible()]
        result['dialog_from_menu'] = bool(found)
        for w in found:
            result['dialog_values'] = [w.first.value(), w.last.value(), w.fps.value(), w.width.value(), w.samples.value(), w.summary.text()]
            w.grab().save(str(out / 'dialog.png'))
            w.reject()
    QtCore.QTimer.singleShot(1500, shut)
    # As the MoonRay menu's entry does. It returns once the dialog is closed.
    lx.eval('moonray.page playblast')


@step(9000)
def realtime():
    panel = panel_widget()
    result['after_cancel'] = [panel._output_busy(), panel.status.text()[:60]]
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))
    QtWidgets.QApplication.processEvents()
    panel.start.click()


@step(3500)
def play():
    note('realtime_on')
    held['before'] = len(held['submits'])
    held['time'] = 0.0

    def tick():
        # As Modo's playing does: the time moved on a frame, a frame's length apart.
        held['time'] += 1 / 24.0
        lx.eval('select.time %s' % held['time'])
    held['tick'] = QtCore.QTimer()
    held['tick'].setInterval(42)
    held['tick'].timeout.connect(tick)
    held['tick'].start()


@step(2500)
def halt():
    held['tick'].stop()
    result['renders_while_playing'] = len(held['submits']) - held['before']
    result['stopped_at'] = round(held['time'] * 24, 1)
    held['before'] = len(held['submits'])
    note('playing')


@step(500)
def finish_():
    result['renders_once_stopped'] = len(held['submits']) - held['before']
    result['last_render'] = held['submits'][-1] if held['submits'] else None
    note('stopped')
    panel_widget().stop()


def run(index=0):
    if index >= len(STEPS):
        save()
        lx.eval('!app.quit')
        return
    function, wait = STEPS[index]
    try:
        function()
    except Exception:
        result.setdefault('errors', []).append([function.__name__, traceback.format_exc()])
        save()
    QtCore.QTimer.singleShot(wait, lambda: run(index + 1))


try:
    import modo
    lx.eval('select.typeFrom item')
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    ball = modo.Scene().selectedByType('mesh')[0]
    ball.position.x.set(-1.0, time=1 / 24.0, key=True)
    ball.position.x.set(1.0, time=4 / 24.0, key=True)
    lx.eval('select.time 0')
    lx.eval('moonray.render.samples 3')
    lx.eval('moonray.render.denoiser 0')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: run())
