# python
"""Isolated GUI test: how the window opens, MoonLightIPR's two buffers, and Draft after an edit.

1. The window opens on MoonRay, showing the crest, and renders nothing.
2. MoonLightIPR chosen with the scene's denoiser off: the list holds Beauty alone.
3. The denoiser switched on: the list offers Denoised Beauty too, and stays on Beauty.
4. Denoised Beauty chosen: the picture is smoother. Beauty chosen again: it is as it was.
5. The ball is moved while realtime is on; Draft switched on draws it where it now is."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/ipr-buffers'
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def rough(image):
    """How grainy a picture is: the mean difference between a pixel and its four neighbours."""
    if image.isNull():
        return None
    image = image.convertToFormat(QtGui.QImage.Format_RGB888)
    w, h, stride = image.width(), image.height(), image.bytesPerLine()
    data = bytes(image.constBits())
    total = count = 0
    for y in range(2, h - 2, 3):
        row = y * stride
        for x in range(2, w - 2, 3):
            i = row + x * 3 + 1
            total += abs(4 * data[i] - data[i - 3] - data[i + 3] - data[i - stride] - data[i + stride])
            count += 1
    return round(total / max(count, 1) / 4.0, 3)


def centre(image):
    """Where what stands out from the background balances, across: moves when what is in the picture moves."""
    if image.isNull():
        return None
    image = image.convertToFormat(QtGui.QImage.Format_RGB888)
    w, h, stride = image.width(), image.height(), image.bytesPerLine()
    data = bytes(image.constBits())
    weight = at = 0
    for y in range(0, h, 4):
        row = y * stride
        edge = data[row + 7]
        for x in range(0, w, 4):
            d = abs(data[row + x * 3 + 1] - edge)
            if d > 20:
                weight += d
                at += d * x
    return round(at / weight / w, 3) if weight else None


def note(name):
    panel = panel_widget()
    image = panel.preview.image
    rows = [panel.buffer.itemText(i) for i in range(panel.buffer.count()) if not panel.buffer.view().isRowHidden(i)]
    result['steps'].append({'step': name, 'engine': panel.preview_engine.currentText(), 'button': panel.start.text(), 'following': panel._following, 'rendering': panel._rendering,
                            'picture': not image.isNull(), 'buffer': panel.buffer.currentText(), 'list': rows, 'grain': rough(image), 'centre': centre(image),
                            'draft': panel.draft.isChecked(), 'status': panel.status.text()})
    panel.preview.grab().save(str(out / ('%02d_%s.png' % (len(result['steps']), name))))
    save()


def choose_buffer(key):
    """As choosing it from the list by hand does."""
    panel = panel_widget()
    index = panel.buffer.findData(key)
    panel.buffer.setCurrentIndex(index)
    panel.buffer.activated.emit(index)


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


@step(4000)
def opened():
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / 'runtime/steady-0351-tiles'))
    note('window_opened')


@step(9000)
def moonlightipr():
    panel = panel_widget()
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))


@step(9000)
def denoiser_on():
    note('moonlightipr_denoiser_off')
    lx.eval('moonray.render.denoiser 1')
    lx.eval('moonray.render.denoise_preview 1')


@step(6000)
def pick_denoised():
    note('denoiser_on')
    choose_buffer('denoised_beauty')


@step(4000)
def pick_beauty():
    note('denoised_chosen')
    choose_buffer('beauty')


@step(6000)
def move():
    note('beauty_chosen_again')
    lx.eval('select.item {%s} set' % held['ball'])
    lx.eval('transform.channel pos.X 0.9')


@step(6000)
def draft():
    note('ball_moved')
    panel_widget().draft.click()


@step(4000)
def draft_off():
    note('draft_on_after_move')
    panel_widget().draft.click()


@step(3000)
def move_back():
    lx.eval('transform.channel pos.X -0.9')


@step(6000)
def draft_again():
    note('ball_moved_back')
    panel_widget().draft.click()


@step(2000)
def to_moonray():
    note('draft_on_again')
    panel = panel_widget()
    panel.draft.click()
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))


@step(25000)
def moonray_render():
    panel_widget().start.click()


@step(5000)
def moonray_draft():
    note('moonray_rendered')
    panel_widget().draft.click()


@step(3000)
def moonray_draft_off_unchanged():
    note('moonray_draft_on')
    panel_widget().draft.click()


@step(5000)
def moonray_draft_again():
    note('moonray_draft_off_scene_unchanged')
    panel_widget().draft.click()


@step(5000)
def moonray_move():
    # Moved with Draft on and nothing pressed: the outlines follow by themselves.
    lx.eval('transform.channel pos.X 0.9')


@step(3000)
def moonray_draft_off_changed():
    note('moonray_draft_on_after_move')
    panel_widget().draft.click()


@step(500)
def finish():
    note('moonray_draft_off_scene_changed')
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
    lx.eval('select.typeFrom item')
    lx.eval('item.create mesh')
    lx.eval('item.name {ball} mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    held['ball'] = next(m.id for m in modo.Scene().items('mesh') if m.name == 'ball')
    lx.eval('moonray.render.denoiser 0')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, run)
