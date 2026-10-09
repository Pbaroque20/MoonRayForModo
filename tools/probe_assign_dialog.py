# python
"""Isolated GUI test: the Assign MoonRay Material dialog, and that what it asks for reaches the scene and the render.

The dialog is opened and pictured, then accepted as it stands. A material is assigned to picked polygons of a cube
with a name, a colour and a smoothing angle, and what Modo holds and what the plugin reads back are written down:
the names in the Shader Tree, the polygon tag, the colour, and the normals of a cube whose faces meet at 90 degrees
under an angle of 40 (flat faces) and of 180 (smoothed together)."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/assign-dialog'
out.mkdir(parents=True, exist_ok=True)
result = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def cube(name, x):
    lx.eval('select.typeFrom item')
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    for key, value in (('cenX', x), ('sizeX', 1.0), ('sizeY', 1.0), ('sizeZ', 1.0), ('segmentsX', 1), ('segmentsY', 1), ('segmentsZ', 1)):
        lx.eval('tool.attr prim.cube %s %s' % (key, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    mesh = modo.Scene().selected[0]
    mesh.name = name
    return mesh


def distinct(normals):
    return len({tuple(round(v, 3) for v in normal) for normal in normals})


try:
    from moonray_modo import geometry, host, materials, material_editor, properties
    scene = modo.Scene()
    first = cube('Box', -1.0)
    result['polygons'] = len(first.geometry.polygons)
    scene.select(first)
    lx.eval('select.typeFrom polygon')
    lx.eval('select.drop polygon')
    for index in (0, 1):
        first.geometry.polygons[index].select()
    result['target'] = materials.target()

    def press():
        dialog = QtWidgets.QApplication.activeModalWidget()
        if dialog is not None:
            dialog.grab().save(str(out / 'dialog.png'))
            result['fields'] = [w.text() for w in dialog.findChildren(QtWidgets.QLabel)] + [w.text() for w in dialog.findChildren(QtWidgets.QCheckBox)]
            dialog.accept()
    QtCore.QTimer.singleShot(800, press)
    result['dialog_gave'] = material_editor.choose(materials.target(), materials.names_in_use())
    made = materials.assign('DwaBaseMaterial', name='Brushed Steel', color=[.8, .1, .1], smoothing=True, angle=40.0)
    held = properties.read(made)
    result['made'] = {'mask': made.parent.name, 'tag': made.parent.channel('ptag').get(), 'material': made.name,
                      'parameters': held.get('native_parameters'), 'smoothing': [held.get('smoothing'), held.get('smoothing_angle')],
                      'wearing': sum(first.geometry.polygons[i].materialTag == made.parent.channel('ptag').get() for i in range(len(first.geometry.polygons)))}
    # The same name again is told apart.
    scene.select(first)
    lx.eval('select.typeFrom polygon')
    lx.eval('select.drop polygon')
    first.geometry.polygons[3].select()
    again = materials.assign('DwaMetalMaterial', name='Brushed Steel', color=[.9, .9, .9], smoothing=False)
    result['again'] = [again.parent.name, again.parent.channel('ptag').get()]
    # A whole cube under each angle.
    for label, angle in (('Sharp', 40.0), ('Round', 180.0)):
        box = cube(label, 2.0 if label == 'Sharp' else 4.0)
        scene.select(box)
        lx.eval('select.typeFrom item')
        scene.select(box)
        materials.assign('DwaBaseMaterial', name=label, smoothing=True, angle=angle)
    plain = cube('Untouched', 6.0)
    snapshot = host.snapshot()
    read = {}
    for mesh in geometry.render_meshes(snapshot['meshes']):
        read[mesh['name']] = {'says': mesh.get('material_smoothing'), 'corners': len(mesh.get('normals') or []), 'different_normals': distinct(mesh.get('normals') or [])}
    result['read_back'] = read
    result['warnings'] = snapshot.get('warnings', [])
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
