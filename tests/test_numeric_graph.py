"""Host checks for typed persistent graph numeric controls."""
import json,sys,unittest,gc
from pathlib import Path
try:
    import modo
    from PySide2 import QtCore,QtGui,QtWidgets
except ImportError:raise unittest.SkipTest('Requires Modo Python/Qt')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import nodes,properties
from moonray_modo.node_editor import Editor
from test_node_editing import key_text,key_click

class NumericGraph(unittest.TestCase):
    def setUp(self):
        self.app=QtWidgets.QApplication.instance()
        self.item=modo.Scene().addMaterial(name='Numeric field validation')
        properties.write(self.item,{'node_graph':nodes.new(),'node_override':True})
        self.editor=Editor(self.item);self.editor.show();self.editor.items['surface'].setSelected(True)
        self.app.processEvents()
    def tearDown(self):
        self.editor.close();self.editor.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
        modo.Scene().removeItems([self.item]);gc.collect()
    def field(self):return next(w for w in self.editor.numeric_fields if w.key=='metallic')
    def type_value(self,text):
        field=self.field();field.setFocus();field.selectAll();key_text(field.lineEdit(),text);return field
    def test_enter_commits_without_replacing_field_or_saving_graph(self):
        field=self.type_value('0.5');key_click(field.lineEdit(),QtCore.Qt.Key_Return);self.app.processEvents()
        self.assertEqual(self.editor.table.item(self.editor.table.currentRow(),0).text(),'metallic')
        self.assertEqual(self.editor.graph['nodes']['surface']['parameters']['metallic'],.5)
        self.assertIs(self.field(),field)
        self.assertIsNone(self.editor.table.itemDelegateForColumn(1).active_editor)
        self.assertNotIn('metallic',properties.read(self.item)['node_graph']['nodes']['surface']['parameters'])
        self.assertFalse(self.editor.material_preview.live.isChecked())
    def test_draft_commits_pending_text_without_tab(self):
        field=self.type_value('0.5');draft=self.editor.preview_draft()
        self.assertEqual(draft['node_graph']['nodes']['surface']['parameters']['metallic'],.5)
        self.assertIs(self.field(),field)
    def test_first_override_receives_value_without_changing_base(self):
        self.editor.graph['overrides']=[{'name':'Override','node':'surface','enabled':True,'parameters':{},'inputs':{}}]
        self.editor.rebuild();self.editor.layers.setCurrentIndex(1)
        field=self.type_value('0.5');key_click(field.lineEdit(),QtCore.Qt.Key_Return);self.app.processEvents()
        self.assertEqual(self.editor.graph['overrides'][0]['parameters']['metallic'],.5)
        self.assertNotIn('metallic',self.editor.graph['nodes']['surface']['parameters'])
    def test_focus_change_commits_typed_value(self):
        field=self.type_value('0.5');self.editor.property_search.setFocus();self.app.processEvents()
        self.assertEqual(self.editor.graph['nodes']['surface']['parameters']['metallic'],.5)
        self.assertIs(self.field(),field)
    def test_color_swatch_uses_native_decoration_without_python_paint(self):
        delegate=self.editor.table.itemDelegateForColumn(1)
        self.assertNotIn('paint',type(delegate).__dict__)
        row=next(r for r in range(self.editor.table.rowCount()) if self.editor.table.item(r,0).text()=='metallic_color')
        cell=self.editor.table.item(row,1)
        self.assertIsInstance(cell.data(QtCore.Qt.DecorationRole),QtGui.QColor)
        cell.setText('[0.8, 0.1, 0.5]')
        self.assertEqual(cell.data(QtCore.Qt.DecorationRole).name(),'#cc1a80')
        self.editor.table.scrollToItem(cell)
        for _ in range(10):
            self.editor.table.viewport().repaint();self.app.processEvents();gc.collect()

    def test_file_icon_does_not_borrow_host_style(self):
        delegate=self.editor.table.itemDelegateForColumn(1)
        cell=QtWidgets.QTableWidgetItem('texture.exr')
        self.editor.style=lambda:(_ for _ in ()).throw(RuntimeError('Deleted host style'))
        delegate.decorate(cell,{'name':'file','type':'String'},'texture.exr')
        icon=cell.data(QtCore.Qt.DecorationRole)
        self.assertIsInstance(icon,QtGui.QIcon)
        self.assertFalse(icon.isNull())

    def test_preview_click_defers_capture_until_mouse_event_returns(self):
        panel=self.editor.material_preview;calls=[]
        panel.capture_snapshot=lambda:(calls.append('capture') or {'render_settings':{}})
        panel.renderer.submit=lambda *args:calls.append('submit')
        panel.viewer.start_requested.emit()
        self.assertEqual(calls,[])
        self.app.processEvents()
        self.assertEqual(calls,['capture','submit'])

if __name__=='__main__':unittest.main()
