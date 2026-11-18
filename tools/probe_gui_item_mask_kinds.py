# python
"""GUI check of group masks naming a Group, a Group Locator or a plain Locator in MoonLightIPR: the scene of
tools/probe_cl_item_mask_kinds.py opened and rendered with MoonLightIPR (a Render), its picture saved as
test-results/item-mask-kinds/moonlightipr.png, for its cubes' colours to be set against Modo's render. Writes
test-results/item-mask-kinds/gui.json. PROBE_FOLDER and PROBE_SCENE name another test folder and scene in it (the bump
scene of tools/probe_cl_item_mask_bump.py: item-mask-bump, bump.lxo)."""
import json
import os
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results') / os.environ.get('PROBE_FOLDER', 'item-mask-kinds')
result = {}
held = {}


def save():
    (out / 'gui.json').write_text(json.dumps(result, indent=1, default=str))


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


def panel():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def setup():
    lx.eval('scene.open {%s} normal' % (out / os.environ.get('PROBE_SCENE', 'item_masks.lxo')))
    lx.eval('moonray.page preview')
    later(3000, start)


def start():
    p = held['panel'] = panel()
    p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonlightipr'))
    later(1500, render)


def render():
    held['panel'].render_once()
    later(1000, lambda: wait(600))


def wait(tries):
    if held['panel']._rendering and tries > 0:
        later(500, lambda: wait(tries - 1))
    else:
        later(2000, finished)


def finished():
    p = held['panel']
    p.preview.image.save(str(out / 'moonlightipr.png'))
    result.update(status=p.status.text(), label=p.image_info.text(), size=(p.preview.image.width(), p.preview.image.height()),
                  notices=[line for line in p.renderer.log.splitlines() if 'mask' in line.lower() or 'material' in line.lower()][:8])
    finish()


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
