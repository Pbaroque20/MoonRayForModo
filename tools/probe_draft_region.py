# python
"""Isolated GUI test: Draft with a region.

With MoonRay chosen and Draft on, a region is set. The outlines are drawn, then the region is rendered among them by
MoonRay, at MoonRay's size. An item is then moved: the outlines and the region are drawn again by themselves. Last, the
same with MoonLightIPR chosen. Each time the picture's size, what was rendered and how many renders it took are noted."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/draft-region'
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}
held = {'submits': 0}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def note(name):
    panel = panel_widget()
    image = panel.preview.image
    part = getattr(panel, '_draft_render', None)
    result['steps'].append({'step': name, 'engine': panel.preview_engine.currentText(), 'draft': panel.draft.isChecked(), 'region': panel._draft_region(),
                            'picture': [image.width(), image.height()], 'region_rendered_at': [part[1].width(), part[1].height()] if part else None,
                            'renders_since_last': held['submits'], 'rendering': panel._rendering, 'status': panel.status.text()[:70], 'info': panel.image_info.text()})
    held['submits'] = 0
    panel.preview.grab().save(str(out / ('%02d_%s.png' % (len(result['steps']), name))))
    save()


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


@step(8000)
def draft_on():
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / 'runtime/steady-0351-tiles'))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    submit = panel.renderer.submit

    def counted(*a, **k):
        held['submits'] += 1
        return submit(*a, **k)
    panel.renderer.submit = counted
    held['item'] = next(m.id for m in modo.Scene().items('mesh'))
    panel.draft.click()


@step(40000)
def region():
    note('draft_on')
    panel = panel_widget()
    # As dragging a rectangle with the Region button does.
    panel.region_enabled.setChecked(True)
    panel._region_drawn(.3, .25, .7, .75)


@step(40000)
def move():
    note('region_set_moonray')
    lx.eval('select.item {%s} set' % held['item'])
    lx.eval('transform.channel pos.X 0.3')


@step(3000)
def moonlightipr():
    note('moved_moonray')
    panel = panel_widget()
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))


@step(12000)
def move_again():
    note('moonlightipr_chosen')
    lx.eval('select.item {%s} set' % held['item'])
    lx.eval('transform.channel pos.X -0.3')


@step(3000)
def region_off():
    note('moved_moonlightipr')
    panel_widget().region_enabled.setChecked(False)


@step(500)
def finish():
    note('region_off')
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
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: run())
