"""The MoonShine graph editor docked in a Modo viewport, as Modo's own Schematic is: a viewport type of its own
(MoonShine Graph, lxserv MoonRayGraphView), and MoonRay > Use Graph Editor in Current Viewport. It shows the graph of
the material selected in Modo, and follows the selection to another; it is the same editor as the window
(node_editor.Editor), embedded."""
from PySide2 import QtCore, QtWidgets


def editable(item):
    """Whether the graph editor edits this item: a MoonRay material whose MoonShine override is on, as Edit Node Graph
    asks (moonray_material_properties.OpenNodes)."""
    from . import material_override, properties
    try:
        kind = item.type
        if not (kind in ('advancedMaterial', 'material.moonrayMoonShine', properties.MATERIALX_TYPE) or properties.layer_shader(item)):
            return False
        return bool(material_override.enabled(properties.read(item)))
    except Exception:
        return False


def chosen_material():
    """The first material selected in Modo that the editor edits: selected itself, or inside a selected material
    group; None where there is none."""
    import modo
    try:
        selected = list(modo.Scene().selected)
    except Exception:
        return None
    for item in selected:
        if editable(item):
            return item
        if item.type == 'mask':
            for child in item.children():
                if editable(child):
                    return child
    return None


class GraphDock(QtWidgets.QWidget):
    """The docked editor: the selected material's graph, or a line saying how to get one."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.editor = None
        self.layout_ = QtWidgets.QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.placeholder = QtWidgets.QLabel('Select a MoonRay material with its MoonShine override on to edit its graph here.')
        self.placeholder.setAlignment(QtCore.Qt.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.layout_.addWidget(self.placeholder)
        # Modo's selection, looked at while the dock is shown: a material chosen there is shown here.
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.follow)
        self.timer.start()
        QtCore.QTimer.singleShot(0, self.follow)

    def follow(self):
        if not self.isVisible():
            return
        if self.editor is not None and (QtWidgets.QApplication.mouseButtons() or self.editor.isAncestorOf(QtWidgets.QApplication.focusWidget())):
            return      # not while the graph is being worked on
        item = chosen_material()
        # Only a change of Modo's selection moves it: a material chosen in the editor's own list stays.
        if item is None or item.id == getattr(self, 'followed', None):
            return
        self.followed = item.id
        if self.editor is None or item.id != self.editor.item.id:
            self.show_material(item)

    def show_material(self, item):
        from .node_editor import Editor
        self.close_editor()
        self.placeholder.hide()
        self.editor = Editor(item, host=self)
        self.editor.finished.connect(self.closed)
        self.layout_.addWidget(self.editor)
        self.editor.show()

    def closed(self, *_):
        editor, self.editor = self.editor, None
        if editor is not None:
            editor.setParent(None)
            editor.deleteLater()
        self.placeholder.show()

    def close_editor(self):
        if self.editor is not None:
            try:
                self.editor.commit_inputs()
            except Exception:
                pass
            editor, self.editor = self.editor, None
            try:
                editor.finished.disconnect(self.closed)
            except (RuntimeError, TypeError):
                pass
            editor.done(0)
            editor.setParent(None)
            editor.deleteLater()

    def dispose(self):
        self.timer.stop()
        self.close_editor()
