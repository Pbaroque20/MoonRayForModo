# python
"""Isolated GUI test: Draft goes off for a render; Denoised Beauty denoises of itself; the mode shown in the corner.

Two balls, no denoiser set in the scene.
1. MoonRay: Draft on, then Render: Draft is off and the picture is rendered.
2. With that render finished, Denoised Beauty is chosen in the list: it is denoised without a denoiser being set, by
   whichever denoiser will run, and nothing is rendered again.
3. A denoiser is chosen and Safe Denoising switched on as the picture's right-click menu does: the foot of the
   picture says so; switched off the same way, it is gone and the scene's setting is off.
4. MoonLightIPR: Draft on, then RT on: Draft is off. Denoised Beauty is in its list with no denoiser set; chosen, the
   engine renders again, denoising."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/modes'
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}
held = {'submits': 0}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def rough():
    """How grainy the picture is: the denoised one is far smoother than the beauty it is of."""
    image = panel_widget().preview.image
    if image.isNull():
        return None
    image = image.convertToFormat(QtGui.QImage.Format_RGB888)
    w, h, stride = image.width(), image.height(), image.bytesPerLine()
    data = bytes(image.constBits())
    total = count = 0
    for y in range(2, h - 2, 5):
        for x in range(2, w - 2, 5):
            i = y * stride + x * 3 + 1
            total += abs(4 * data[i] - data[i - 3] - data[i + 3] - data[i - stride] - data[i + stride]); count += 1
    return round(total / max(count, 1) / 4.0, 2)


def note(name):
    panel = panel_widget()
    frame = panel.renderer.buffers.frame or {}
    rows = [panel.buffer.itemData(i) for i in range(panel.buffer.count()) if not panel.buffer.view().isRowHidden(i)]
    result['steps'].append({'step': name, 'engine': panel.preview_engine.currentText(), 'draft': panel.draft.isChecked(), 'button': panel.start.text(),
                            'rendering': panel._rendering, 'following': panel._following, 'buffer': panel.buffer.currentData(), 'rough': rough(),
                            'renders': held['submits'], 'denoised_file': 'denoised_beauty' in frame.get('files', {}), 'denoise_engine': frame.get('denoise_engine'),
                            'rows_listed': rows if len(rows) < 6 else len(rows), 'hud': panel.hud.text() if panel.hud.isVisible() else None,
                            'ipr_denoising': getattr(panel.renderer, 'moonlightipr_denoises', None), 'status': panel.status.text()[:70]})
    panel.preview.grab().save(str(out / ('%02d_%s.png' % (len(result['steps']), name))))
    save()


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


@step(4000)
def draft_on():
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / 'runtime/steady-0351-tiles'))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    submit = panel.renderer.submit

    def counted(*a, **k):
        held['submits'] += 1
        return submit(*a, **k)
    panel.renderer.submit = counted
    panel.draft.click()


@step(60000)
def press_render():
    note('draft_on_moonray')
    panel_widget().start.click()


@step(15000)
def choose_denoised():
    note('rendered_after_draft')
    panel = panel_widget()
    held['before'] = held['submits']
    index = panel.buffer.findData('denoised_beauty')
    panel.buffer.setCurrentIndex(index); panel._buffer_picked = 'denoised_beauty'


@step(3000)
def safe_on():
    note('denoised_beauty_chosen_no_denoiser_set')
    result['renders_for_denoising'] = held['submits'] - held['before']
    lx.eval('moonray.render.denoiser 2')
    # As the picture's right-click menu does.
    panel_widget()._safe_toggled(True)


@step(2000)
def hud_off():
    note('safe_denoising_on')
    panel_widget()._safe_toggled(False)
    result['safe_after_off'] = lx.eval('moonray.render.denoise_safe ?')


@step(2000)
def moonlightipr():
    note('corner_switched_off')
    panel = panel_widget()
    lx.eval('moonray.render.denoiser 0')
    panel._buffer_picked = None
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))
    QtWidgets.QApplication.processEvents()
    panel.draft.click()


@step(5000)
def rt_on():
    note('draft_on_moonlightipr')
    panel_widget().start.click()


@step(7000)
def ipr_denoised():
    note('rt_on_after_draft')
    panel = panel_widget()
    held['before'] = held['submits']
    index = panel.buffer.findData('denoised_beauty')
    result['ipr_denoised_listed'] = index >= 0 and not panel.buffer.view().isRowHidden(index)
    panel.buffer.setCurrentIndex(index); panel._buffer_picked = 'denoised_beauty'


@step(500)
def finish_():
    note('moonlightipr_denoised_chosen')
    result['renders_for_ipr_denoising'] = held['submits'] - held['before']
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
    for x in (-.6, .6):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.sphere on')
        lx.eval('tool.attr prim.sphere cenX %s' % x)
        lx.eval('tool.apply')
        lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.render.samples 3')
    lx.eval('moonray.render.denoiser 0')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: run())
