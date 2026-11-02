# python
"""Isolated GUI test: the kit's commands that follow the selection are asked for their clients, and a material's value on an open
form changes when written, with the mouse left alone. Writes test-results/followed/report.json and its pictures."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets
from moonray_modo import properties, property_notifications

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/followed'
out.mkdir(parents=True, exist_ok=True)
result = {'clients': {}}
held = {}
add_client = property_notifications.Followed.cmd_NotifyAddClient


def counted(self, argument, client):
    name = type(self).__name__
    result['clients'][name] = result['clients'].get(name, 0) + 1
    try:
        add_client(self, argument, client)
    except Exception:
        result.setdefault('failed', {})[name] = traceback.format_exc()
        raise


property_notifications.Followed.cmd_NotifyAddClient = counted


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def picture(name):
    QtWidgets.QApplication.primaryScreen().grabWindow(0).save(str(out / (name + '.png')))


def guarded(call):
    def run():
        try:
            call()
        except Exception:
            result['error'] = traceback.format_exc()
            save()
            lx.eval('!app.quit')
    return run


def asked():
    return lx.eval('moonray.material.thin ?')


def thin(value):
    lx.eval('!moonray.material.thin %d' % value)


def step_mesh():
    lx.eval('select.item {%s} set' % held['mesh'].id)
    QtCore.QTimer.singleShot(2000, guarded(step_mtlx))


def step_mtlx():
    lx.eval('select.item {%s} set' % held['mtlx'].id)
    QtCore.QTimer.singleShot(2000, guarded(step_material))


def step_material():
    picture('mtlx')
    lx.eval('select.item {%s} set' % held['material'].id)
    QtCore.QTimer.singleShot(2000, guarded(step_before))


def step_before():
    result['thin before'] = asked()
    picture('before')
    thin(True)
    QtCore.QTimer.singleShot(1500, guarded(step_after))


def step_after():
    result['thin after'] = asked()
    picture('after')
    thin(False)
    result['done'] = True
    save()
    QtCore.QTimer.singleShot(200, lambda: lx.eval('!app.quit'))


try:
    scene = modo.Scene()
    held['mesh'] = scene.addMesh('Followed mesh')
    held['material'] = scene.addMaterial(name='Followed material')
    held['mtlx'] = scene.addItem(properties.MATERIALX_TYPE)
    lx.eval('select.item {%s} set' % held['material'].id)
    QtCore.QTimer.singleShot(3000, guarded(step_mesh))
    lx.eval('attr.formPopover {MoonShineLegacyProperties:sheet}')
except Exception:
    result['open'] = traceback.format_exc()
    save()
