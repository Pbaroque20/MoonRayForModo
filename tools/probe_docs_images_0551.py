# python
"""Pictures for the docs (0.5.5.1), from a test Modo: Render Settings' XPU and XPU2 Outputs (AOVs) and MoonLightIPR
Outputs (AOVs), each section of the Render item's MoonRay form opened on its own as a popover, in a new scene (Alpha
alone ticked, as a new scene has it). Writes test-results/docs-images-0551/ (render-settings-aovs-xpu.png,
render-settings-aovs-moonlightipr.png and report.json with what each popover held)."""
import json
import pathlib
import shutil
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/docs-images-0551'
shutil.rmtree(out, ignore_errors=True)
out.mkdir(parents=True, exist_ok=True)
result = {'shots': {}}
held = {'to do': [('MoonRayRender_11:sheet', 'render-settings-aovs-xpu'),
                  ('MoonRayRenderMoonLightIPRAOVs:sheet', 'render-settings-aovs-moonlightipr')]}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def guarded(step):
    def run():
        try:
            step()
        except Exception:
            result.setdefault('errors', []).append(step.__name__ + ': ' + traceback.format_exc())
            finish()
        save()
    return run


def later(ms, step):
    QtCore.QTimer.singleShot(ms, guarded(step))


def shown():
    return {id(w): w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()}


def setup():
    lx.eval('select.item {%s} set' % modo.Scene().renderItem.id)
    later(2000, next_shot)


def next_shot():
    if not held['to do']:
        finish()
        return
    sheet, name = held['now'] = held['to do'].pop(0)
    held['before'] = shown()
    try:
        lx.eval('attr.formPopover {%s}' % sheet)
    except Exception as exc:
        result['shots'][name] = 'popover failed: %s' % exc
        later(500, next_shot)
        return
    later(2500, grab)


def grab():
    sheet, name = held['now']
    new = [w for key, w in shown().items() if key not in held['before']]
    result['shots'][name] = [(type(w).__name__, w.objectName(), w.width(), w.height()) for w in new]
    if new:
        window = max(new, key=lambda w: w.width() * w.height())
        window.grab().save(str(out / (name + '.png')))
        window.close()
    later(1500, next_shot)


def finish():
    if held.get('finished'):
        return
    held['finished'] = True
    result['done'] = True
    save()
    QtCore.QTimer.singleShot(1000, lambda: lx.eval('!app.quit'))


save()
# Scene edits here, at the probe's top level: Modo refuses them from a Qt timer.
guarded(setup)()
