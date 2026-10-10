# python
"""Isolated GUI test: the scene controls dialog keeps which objects an object casts no shadow onto.

Two meshes are made. The dialog is opened on what the scene holds, one mesh is chosen, the other ticked in its list of
objects it casts no shadow onto, and the dialog saved; what comes back, and the line the scene written for MoonRay has
for it, are written down."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/shadow-receivers'
out.mkdir(parents=True, exist_ok=True)
result = {}
try:
    from moonray_modo import host, rdla
    from moonray_modo.production_dialog import Controls
    made = []
    for name, height in (('Ground', -.05), ('Crate', .5)):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.cube on')
        lx.eval('tool.attr prim.cube cenY %s' % height)
        lx.eval('tool.apply')
        lx.eval('tool.set prim.cube off')
        mesh = modo.Scene().selected[0]
        mesh.name = name
        made.append(mesh)
    ground, crate = made
    dialog = Controls({})
    pick = dialog.selectors['objects']
    pick.setCurrentIndex(pick.findData(crate.id))
    listed = dialog.lists['shadow_receivers']
    result['listed'] = [listed.item(i).text() for i in range(listed.count())]
    for i in range(listed.count()):
        if listed.item(i).data(QtCore.Qt.UserRole) == ground.id:
            listed.item(i).setCheckState(QtCore.Qt.Checked)
    dialog._accept()
    kept = dialog.values['objects'].get(crate.id, {})
    result['kept'] = kept.get('shadow_receivers') == [ground.id]
    # Opened again on what was saved, the tick is still there.
    again = Controls(dialog.values)
    again.selectors['objects'].setCurrentIndex(again.selectors['objects'].findData(crate.id))
    result['shown_again'] = [again.lists['shadow_receivers'].item(i).text() for i in range(again.lists['shadow_receivers'].count())
                             if again.lists['shadow_receivers'].item(i).checkState() == QtCore.Qt.Checked]
    taken = host.snapshot(refresh_materials=True)
    taken['production'] = dialog.values
    text = rdla.scene_text(taken, 160, 90, 2, 0.5, str(out / 'check.exr'))
    result['written'] = [line.strip() for line in text.splitlines() if 'ShadowReceiverSet(' in line]
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
