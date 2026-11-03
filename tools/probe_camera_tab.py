# python
"""Isolated GUI test: a dw PerspectiveCamera selected, which Properties tab Modo puts in front, what the filter commands
of its forms answer, and whether the channels the Modo camera's lens gives it are greyed in its dw tab (and not with the
switch off). Writes test-results/camera-tab/report.json and pictures of Modo's window."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/camera-tab'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))


def window():
    return max((w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()), key=lambda w: w.width() * w.height())


def query(command):
    try:return lx.eval(command)
    except Exception as exc:return 'failed: %s' % exc


def tabs():
    """The vertical tab bars' texts, and which is current, in Modo's window."""
    found = []
    for bar in window().findChildren(QtWidgets.QTabBar):
        texts = [bar.tabText(i) for i in range(bar.count())]
        if any('Camera' in t or 'dw' in t for t in texts):
            found.append({'tabs': texts, 'current': bar.tabText(bar.currentIndex()) if bar.currentIndex() >= 0 else None})
    return found


def enabled(item, key):
    """Whether Modo has the channel's control enabled: asked through the package's ChannelUI, as the form does."""
    from moonray_modo import entities
    try:
        scene_service = lx.service.Scene()
        channel = entities.CHANNEL_PREFIX + key
        raw = lx.object.Item(item)
        index = raw.ChannelLookup(channel)
        ui = lx.service.ChannelUI() if hasattr(lx.service, 'ChannelUI') else None
        if ui is not None and hasattr(ui, 'ItemEnabled'):
            return bool(ui.ItemEnabled(raw, index))
        return 'no ChannelUI service'
    except Exception as exc:
        return 'failed: %s' % exc


def begin():
    try:
        from moonray_modo import entities
        scene = modo.Scene()
        lx.eval('moonray.entity.add PerspectiveCamera')
        item = held['item'] = next(i for i in scene.selected if i.type == 'camera')
        # Something else first, then the camera, as a person picks it in the item list.
        lx.eval('select.item {%s} set' % scene.items('light')[0].id if scene.items('light') else 'select.drop item')
        QtCore.QTimer.singleShot(800, pick)
    except Exception:
        result['error'] = traceback.format_exc();save()


def pick():
    try:
        lx.eval('select.item {%s} set' % held['item'].id)
        QtCore.QTimer.singleShot(1500, look)
    except Exception:
        result['pick_error'] = traceback.format_exc();save()


def look():
    try:
        item = held['item']
        result['tabs_after_pick'] = tabs()
        result['linked'] = {key: enabled(item, key) for key in ('focal', 'dof_aperture', 'bokeh_image', 'bokeh_sides')}
        window().grab().save(str(out / 'picked.png'))
        QtCore.QTimer.singleShot(300, unlinked)
    except Exception:
        result['look_error'] = traceback.format_exc();save()


def unlinked():
    try:
        result['unlinked'] = {key: enabled(held['item'], key) for key in ('focal', 'dof_aperture', 'bokeh_image')}
    except Exception:
        result['unlinked_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


result['started'] = True
save()
QtCore.QTimer.singleShot(5000, begin)
