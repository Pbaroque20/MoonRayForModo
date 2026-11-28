# python
"""One DWA material, its graph editor opened and closed (or never opened, PROBE_NO_EDITOR=1), then quit: the exit code
tells whether quitting crashes (1 is a clean exit). With b91bd8c0 it crashed, 0xC0000005, whenever the test Modo was
in the background: node_editor._modo_window looked through Modo's windows for a parent (QApplication.topLevelWidgets)."""
import os
import lx
from PySide2 import QtCore
lx.eval('scene.new')
from moonray_modo import properties
import modo
scene = modo.Scene()
cube = scene.addMesh('Q')
lx.eval('select.item {%s} set' % cube.id)
lx.eval('poly.setMaterial Q')
mask = [i for i in scene.items('mask') if i.name.startswith('Q')][0]
lx.eval('select.item {%s} set' % mask.id)
lx.eval('shader.create advancedMaterial')
material = [i for i in scene.selected if i.type == 'advancedMaterial'][-1]
settings = properties.read(material)
settings.update(moonshine_override=True, native_shader='DwaBaseMaterial', shader='DwaBaseMaterial', native_parameters={})
properties.write(material, settings)
def close():
    from moonray_modo import node_editor
    for editor in list(node_editor._open.values()):
        editor.close()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))
if os.environ.get('PROBE_NO_EDITOR'):
    QtCore.QTimer.singleShot(3000, lambda: lx.eval('!app.quit'))
else:
    lx.eval('select.item {%s} set' % material.id)
    lx.eval('moonray.material.nodes')
    QtCore.QTimer.singleShot(4000, close)
