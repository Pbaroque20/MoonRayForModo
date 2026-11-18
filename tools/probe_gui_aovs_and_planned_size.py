# python
"""GUI check of two things in the preview window:

1. Render Settings' AOV sections decide the buffer list: XPU and XPU2 Outputs (AOVs) for MoonRay, MoonLightIPR Outputs
   (AOVs) for MoonLightIPR, Alpha alone ticked in a new scene; a tick (the form's own command) lists its buffer at once.
2. The size said beside the picture follows the scene: two scenes open (640 x 360 saved, then 1000 x 500 new), the
   label read in each, after switching between them and after the resolution is changed.

Writes test-results/aovs-and-planned-size/report.json."""
import json
import pathlib
import shutil
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/aovs-and-planned-size'
shutil.rmtree(out, ignore_errors=True)
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


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


def scene_at(width, height):
    # The size is all that is looked at: no geometry is needed.
    scene = modo.Scene()
    scene.renderItem.channel('resX').set(width)
    scene.renderItem.channel('resY').set(height)
    return scene


def setup():
    scene_at(640, 360)
    path = out / 'small.lxo'
    lx.eval('scene.saveAs {%s} $LXOB false' % path)
    held['small'] = str(path)
    lx.eval('!scene.close')
    lx.eval('scene.new')
    scene_at(1000, 500)
    held['big'] = modo.Scene().name
    lx.eval('moonray.page preview')
    later(3000, start)


def panel():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def listed():
    p = panel()
    return [p.buffer.itemData(row) for row in range(p.buffer.count()) if not p.buffer.view().isRowHidden(row)]


def start():
    p = panel()
    p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonray'))
    result['planned share'] = p.preferences.get('preview_fraction')
    result['label, 1000 x 500 scene'] = p.image_info.text()
    result['moonray list, new scene'] = listed()
    lx.eval('moonray.render.aov_depth 1')
    later(1200, ticked_moonray)


def ticked_moonray():
    result['moonray list, depth ticked'] = listed()
    p = panel()
    p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonlightipr'))
    later(800, moonlightipr_list)


def moonlightipr_list():
    result['moonlightipr list, new scene'] = listed()
    lx.eval('moonray.render.moonlightipr_aov_moonlightipr_diffuse 1')
    later(1200, ticked_moonlightipr)


def ticked_moonlightipr():
    result['moonlightipr list, diffuse ticked'] = listed()
    lx.eval('moonray.render.moonlightipr_aov_alpha 0')
    later(1200, unticked_alpha)


def unticked_alpha():
    result['moonlightipr list, alpha unticked'] = listed()
    panel().preview_engine.setCurrentIndex(panel().preview_engine.findData('moonray'))
    # A scene opened from its file: its own size said.
    lx.eval('!scene.open {%s} normal' % held['small'])
    later(1500, switched)


def switched():
    result['scene now'] = modo.Scene().name
    result['label, 640 x 360 scene opened'] = panel().image_info.text()
    lx.eval('!scene.set {%s}' % held['big'])
    later(1500, back)


def back():
    result['scene back'] = modo.Scene().name
    result['label, back to 1000 x 500'] = panel().image_info.text()
    lx.eval('render.res 0 1200')
    lx.eval('render.res 1 300')
    later(1500, resized)


def resized():
    result['render item now'] = (modo.Scene().renderItem.channel('resX').get(), modo.Scene().renderItem.channel('resY').get())
    result['label, resized to 1200 x 300'] = panel().image_info.text()
    finish()


def finish():
    if held.get('finished'):
        return
    held['finished'] = True
    result['done'] = True
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


save()
guarded(setup)()
