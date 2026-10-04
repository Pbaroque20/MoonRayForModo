"""Qt event-level parameter editing checks; uses Modo's bundled PySide2."""
import json,sys,unittest,gc,weakref
from pathlib import Path
try:
    from PySide2 import QtCore,QtWidgets,QtGui
except ImportError:raise unittest.SkipTest('Requires Modo-compatible PySide2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo.node_widgets import ParameterDelegate
def key_click(widget,key,text=''):
    for kind in (QtCore.QEvent.KeyPress,QtCore.QEvent.KeyRelease):
        QtWidgets.QApplication.sendEvent(widget,QtGui.QKeyEvent(kind,key,QtCore.Qt.NoModifier,text))
def key_text(widget,text):
    for character in text:key_click(widget,ord(character.upper()),character)
class Dummy(QtWidgets.QWidget):
    def __init__(self):
        super().__init__();self.graph={'nodes':{'m':{'type':'DwaBaseMaterial'}}}
        self.table=QtWidgets.QTableWidget(1,2,self);self.table.setGeometry(0,0,350,180)
        self.table.setItem(0,0,QtWidgets.QTableWidgetItem('metallic'));self.table.setItem(0,1,QtWidgets.QTableWidgetItem('0.0'))
        self.delegate=ParameterDelegate(self);self.table.setItemDelegateForColumn(1,self.delegate)
        self.resize(400,200)
    def selected(self):return 'm'
class MetallicEditing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def test_repeated_valid_values_enter_tab_and_close(self):
        for i in range(40):
            window=Dummy();window.show();self.app.processEvents()
            for text,key in [('0.5',QtCore.Qt.Key_Return),('1.0',QtCore.Qt.Key_Tab),('0.0',QtCore.Qt.Key_Return)]:
                window.table.editItem(window.table.item(0,1));self.app.processEvents()
                spin=window.delegate.active_editor;self.assertIsNotNone(spin)
                spin.setFocus();spin.selectAll();key_text(spin,text);key_click(spin,key)
                self.app.processEvents();self.assertAlmostEqual(float(window.table.item(0,1).text()),float(text))
            window.close();window.deleteLater();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
    def test_pending_focus_commit_survives_table_reset(self):
        for i in range(20):
            window=Dummy();window.show();window.table.editItem(window.table.item(0,1));self.app.processEvents()
            spin=window.delegate.active_editor;spin.setFocus();spin.selectAll();key_text(spin,'0.5')
            window.table.clearContents();window.close();window.deleteLater()
            self.app.processEvents();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
    def test_closed_editor_does_not_commit_again_or_remain_referenced(self):
        window=Dummy();window.show();self.app.processEvents()
        commits=[];window.delegate.commitData.connect(lambda widget:commits.append(widget.value()))
        window.table.editItem(window.table.item(0,1));self.app.processEvents()
        spin=window.delegate.active_editor;spin.setValue(.5);reference=weakref.ref(spin)
        window.delegate.pending_focus=reference;window.delegate.focus_timer.start(0)
        window.delegate.commit_pending()
        self.assertEqual(commits,[.5]);self.assertIsNone(window.delegate.active_editor)
        self.assertFalse(window.delegate.focus_timer.isActive())
        self.app.processEvents();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
        del spin;gc.collect()
        self.assertIsNone(reference());self.assertEqual(commits,[.5])
        window.close();window.deleteLater()

    def test_old_editor_cleanup_preserves_new_pending_focus(self):
        window=Dummy();window.show();self.app.processEvents()
        old=QtWidgets.QDoubleSpinBox(window.table)
        window.table.editItem(window.table.item(0,1));self.app.processEvents()
        current=window.delegate.active_editor
        window.delegate.pending_focus=weakref.ref(current);window.delegate.focus_timer.start(0)
        window.delegate.detach_editor(old)
        self.assertIs(window.delegate.active_editor,current)
        self.assertIs(window.delegate.pending_focus(),current)
        self.assertTrue(window.delegate.focus_timer.isActive())
        window.delegate.commit_pending();old.deleteLater();window.close();window.deleteLater()

if __name__=='__main__':unittest.main()