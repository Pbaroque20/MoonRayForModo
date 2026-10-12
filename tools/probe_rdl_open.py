# python
"""Isolated GUI test: a MoonRay scene opened with Modo's own File > Open.

scene.open is given veach-mis/scene.rdla, as choosing it in File > Open does: a scene is made, the importer reads the file into it by itself, and what the scene then holds
is counted. A file that is not a MoonRay scene (an .lxo) must still open as it always did."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/rdl-open'
out.mkdir(parents=True, exist_ok=True)
result = {}
source = root / 'downloads/moonray-example-scenes/scenes/veach-mis/scene.rdla'


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def count():
    scene = modo.Scene()
    kinds = {}
    for item in scene.items():
        kinds[item.type] = kinds.get(item.type, 0) + 1
    return {'file': scene.filename, 'meshes': kinds.get('mesh', 0), 'cameras': kinds.get('camera', 0),
            'empty_meshes': sum(1 for m in scene.items('mesh') if not len(m.geometry.polygons)),
            'moonray_items': sum(n for kind, n in kinds.items() if kind.startswith('moonray.')),
            'polygons': sum(len(m.geometry.polygons) for m in scene.items('mesh'))}


def begin():
    try:
        import faulthandler
        held = open(str(out / 'stuck.txt'), 'wb', 0)
        result['_held'] = None
        globals()['_stuck'] = held
        faulthandler.dump_traceback_later(15, repeat=True, file=held)
        result['before'] = count()
        lx.eval('scene.open {%s} normal' % source)
        result['just_opened'] = count()
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(25000, after)


def after():
    try:
        from moonray_modo import rdl_import_dialog
        dialog = rdl_import_dialog._dialog
        result['after'] = count()
        result['dialog'] = {'shown': bool(dialog and dialog.isVisible()), 'says': dialog.report.toPlainText()[:400] if dialog else None}
        if dialog:
            dialog.grab().save(str(out / 'dialog.png'))
            dialog.close()
        # Something that is not a MoonRay scene still opens as it did.
        other = pathlib.Path(r'C:\Users\Raphael Tobar\Downloads\cheetah_moonray.lxo')
        lx.eval('scene.open {%s} normal' % other)
        result['plain_scene'] = count()
    except Exception:
        result['after_error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')


save()
QtCore.QTimer.singleShot(6000, begin)
