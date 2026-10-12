# python
"""Isolated GUI test: what a MoonRay rect light's properties look like (issue 43: the link between width and height).

A dwRectLight is added and selected, and every window that is up is saved as a picture, once with the item selected
and once after its width has been changed by command, to see whether the height followed."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/light-form'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def shot(name):
    for index, window in enumerate(w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible() and w.width() > 300):
        window.grab().save(str(out / ('%s-%d.png' % (name, index))))


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


try:
    from moonray_modo import entities
    scene = modo.Scene()
    item = scene.addItem(entities.item_type('RectLight'), name='dwRectLight')
    for key, value in entities.starting('RectLight').items():
        try:
            item.channel(entities.CHANNEL_PREFIX + key).set(value)
        except Exception:
            pass
    held['item'] = item.id
    lx.eval('select.item {%s} set' % item.id)
    result['channels'] = {name: item.channel(name).get() for name in item.channelNames if 'width' in name.lower() or 'height' in name.lower()}
    # The item's own sheet, in a window of its own: in a new profile the Properties panel opens on its Display tab.
    for attempt in ('attr.formPopover {MoonRayEntity21:sheet}', 'attr.formPopover {MoonRayEntity_RectLight_1:sheet}'):
        try:
            lx.eval(attempt)
            result.setdefault('popped', []).append(attempt)
        except Exception as exc:
            result.setdefault('not_popped', []).append('%s: %s' % (attempt, str(exc)[:80]))
except Exception:
    result['error'] = traceback.format_exc()
save()


def step2():
    try:
        shot('selected')
        item = modo.Scene().item(held['item'])
        names = [n for n in item.channelNames if 'width' in n.lower()]
        result['width_channel'] = names
        if names:
            lx.eval('select.item {%s} set' % item.id)
            lx.eval('item.channel {%s} 3.0' % names[0])
            result['after'] = {name: item.channel(name).get() for name in item.channelNames if 'width' in name.lower() or 'height' in name.lower()}
    except Exception:
        result['step2_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(2500, step3)


def step3():
    try:
        shot('edited')
    except Exception:
        result['step3_error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')


QtCore.QTimer.singleShot(8000, step2)
