# python
"""Isolated GUI test: a dw camera that uses the Modo camera's lens. A new dwPerspectiveCamera is given a lens in Modo's
own channels; the evaluated Modo channels and what the render reads are written down, then the same with the switch
off (the MoonRay lens drives Modo's again). Writes test-results/camera-modo-lens/report.json and a picture of its form."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/camera-modo-lens'
out.mkdir(parents=True, exist_ok=True)
result = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def reading(item):
    from moonray_modo import entities, host
    snapshot = host.snapshot()
    entity = next(e for e in snapshot['entities'] if e['identity'] == item.id)
    return {'evaluated': {name: item.channel(name).get() for name in ('focalLen', 'apertureX', 'filmFit', 'fStop')},
            'rendered': {key: entity['parameters'].get(key) for key in ('focal', 'film_width_aperture', 'dof', 'dof_aperture',
                                                                      'dof_focus_distance', 'bokeh_sides', 'stereo_view')},
            'shutter': [snapshot['camera'].get('shutter_length'), snapshot['camera'].get('shutter_offset')]}


def finish():
    try:
        # Modo's own window only, never the screen behind it.
        window = max((w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()), key=lambda w: w.width() * w.height())
        window.grab().save(str(out / 'form.png'))
    except Exception:
        result['picture'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(300, lambda: lx.eval('!app.quit'))


try:
    from moonray_modo import entities
    scene = modo.Scene()
    lx.eval('moonray.entity.add PerspectiveCamera')
    item = next(i for i in scene.selected if i.type == 'camera')
    result['modo_lens'] = item.channel(entities.CHANNEL_PREFIX + 'modo_lens').get()
    lx.eval('render.camera {%s}' % item.id)
    for name, value in (('focalLen', 0.024), ('dof', True), ('fStop', 1.4), ('focusDist', 2.5), ('irisBlades', 5), ('blurLen', 0.3)):
        item.channel(name).set(value)
    item.channel(entities.CHANNEL_PREFIX + 'focal').set(80.0)
    result['linked'] = reading(item)
    item.channel(entities.CHANNEL_PREFIX + 'modo_lens').set(False)
    result['unlinked'] = reading(item)
    item.channel(entities.CHANNEL_PREFIX + 'modo_lens').set(True)
    result['linked_again'] = reading(item)
    scene.select(item)
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(5000, finish)
