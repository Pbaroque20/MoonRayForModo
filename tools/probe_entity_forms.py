# python
"""Isolated GUI test: the properties of MoonRay's own items hold nothing to type into. Each attribute that was a text box is
queried and set through its popup, and the forms are pictured."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/entity-forms'
out.mkdir(parents=True, exist_ok=True)
result = {'options': {}}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def windows(name):
    for index, window in enumerate(w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible() and w.width() > 300):
        window.grab().save(str(out / ('%s-%d.png' % (name, index))))


try:
    from moonray_modo import entities
    scene = modo.Scene()
    names = entities.classes()
    scene.addMesh('Subject')
    lx.eval('!poly.setMaterial Skin {0.8 0.5 0.3} 0.8 0.04 true false')
    for kind in ('FisheyeCamera', 'VdbGeometry', 'SpotLight', 'BaseVolume', 'BakeCamera', 'MeshLight'):
        held[kind] = scene.addItem(entities.item_type(kind), name=kind)
    held['SpotLight'].channel(entities.CHANNEL_PREFIX + 'label').set('key')
    for kind, item in held.items():
        scene.select(item)
        i = names.index(kind)
        found = {}
        for j, (key, channel, plan, default, choices) in enumerate(entities.channels(kind)):
            shown = entities.presentation(kind, key)
            if plan == 'string':
                found[key] = shown
            if shown in ('file', 'grid', 'label', 'material', 'uv'):
                command = 'moonray.entity.option%d_%d' % (i, j)
                try:
                    before = lx.eval(command + ' ?')
                    # The first thing offered after "(none)", where there is one.
                    lx.eval(command + ' 1')
                    found[key] = [shown, before, lx.eval(command + ' ?'), item.channel(channel).get()]
                except Exception as exc:
                    found[key] = [shown, 'error', str(exc)[:160]]
        result['options'][kind] = found
    scene.select(held['VdbGeometry'])
except Exception:
    result['error'] = traceback.format_exc()
save()


def step2():
    try:
        windows('vdb')
        modo.Scene().select(held['FisheyeCamera'])
    except Exception:
        result['step2_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(2500, step3)


def step3():
    try:
        windows('fisheye')
    except Exception:
        result['step3_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(5000, step2)
