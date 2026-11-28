"""The MoonShine graph editor docked in a Modo viewport, as Modo's own Schematic is: a viewport type of its own
(MoonShine Graph, lxserv MoonRayGraphView), and MoonRay > Use Graph Editor in Current Viewport. It shows the graph of
the material selected in Modo, and follows the selection to another; it is the same editor as the window
(node_editor.Editor), embedded."""
from PySide2 import QtCore, QtWidgets

PLACEHOLDER = 'Select a MoonRay material with its MoonShine override on to edit its graph here.'


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
    """The docked editor: the selected material's graph, or a line saying how to get one. picker: a list of the scene's
    materials with a graph under that line, to open one from (GraphWindow: MoonRay > Open MoonShine Graph Editor)."""
    def __init__(self, parent=None, picker=False):
        super().__init__(parent)
        self.editor = None
        self.layout_ = QtWidgets.QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.placeholder = QtWidgets.QLabel(PLACEHOLDER)
        self.placeholder.setAlignment(QtCore.Qt.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.picker = None
        # What shows while no graph does: the line, and under it the list (picker); hidden while the editor shows.
        self.empty = self.placeholder
        if picker:
            self.empty = QtWidgets.QWidget()
            box = QtWidgets.QVBoxLayout(self.empty)
            box.addStretch(1)
            box.addWidget(self.placeholder)
            row = QtWidgets.QHBoxLayout()
            row.addStretch(1)
            self.picker = QtWidgets.QComboBox()
            self.picker.setMinimumWidth(320)
            self.picker.setToolTip('A material of this scene with a MoonShine graph, to edit here')
            self.picker.activated.connect(self.picked)
            row.addWidget(self.picker)
            row.addStretch(1)
            box.addLayout(row)
            box.addStretch(1)
            self.fill_picker()
        self.layout_.addWidget(self.empty)
        # Modo's selection, looked at while the dock is shown: a material chosen there is shown here.
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.follow)
        self.timer.start()
        QtCore.QTimer.singleShot(0, self.follow)

    def fill_picker(self):
        """The list: the scene's materials with a graph (node_editor.graph_materials), under a first line asking for one."""
        if self.picker is None:
            return
        from .node_editor import graph_materials
        found = graph_materials()
        blocker = QtCore.QSignalBlocker(self.picker)
        self.picker.clear()
        self.picker.addItem('Choose a material...' if found else 'No material in this scene has a MoonShine graph', None)
        for label, item in found:
            self.picker.addItem(label, item.id)
        self.picker.setCurrentIndex(0)
        del blocker

    def picked(self, index):
        identity = self.picker.itemData(index)
        if not identity:
            return
        import modo
        try:
            item = modo.Scene().item(identity)
        except LookupError:
            self.fill_picker()
            return
        # Chosen here: kept until Modo's selection moves to another material (follow).
        self.followed = item.id
        self.show_material(item)

    def follow(self):
        if not self.isVisible():
            return
        if self.editor is None and self.picker is not None and self.picker.view().isVisible():
            return      # not while the list is open
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
        from .node_editor import Editor, open_failed
        self.close_editor()
        try:
            editor = Editor(item, host=self)
        except Exception as exc:
            # Said once, not left blank (node_editor.open_failed); the dock waits for another material to be selected.
            self.followed = item.id
            self.placeholder.setText('The graph of %s could not be shown here; the reason is in the Event Log.' % item.name)
            self.empty.show()
            open_failed(item, exc, self)
            return
        self.placeholder.setText(PLACEHOLDER)
        self.empty.hide()
        self.editor = editor
        self.editor.finished.connect(self.closed)
        self.layout_.addWidget(self.editor)
        self.editor.show()

    def closed(self, *_):
        # The material's scene closed, or the editor was closed: the next selection is followed afresh (ids repeat from
        # one scene to the next).
        self.followed = None
        editor, self.editor = self.editor, None
        if editor is not None:
            editor.setParent(None)
            editor.deleteLater()
        self.fill_picker()
        self.empty.show()

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


class GraphWindow(QtWidgets.QWidget):
    """MoonRay > Open MoonShine Graph Editor: the graph editor in a window of its own with no graph in it yet: the
    material selected in Modo (as the docked editor follows it), or one chosen from its list. One at a time."""
    def __init__(self, parent=None):
        super().__init__(parent, QtCore.Qt.Window)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setWindowTitle('MoonShine Graph Editor')
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        self.dock = GraphDock(self, picker=True)
        layout.addWidget(self.dock)
        self.resize(1200, 760)

    def closeEvent(self, event):
        # The editor's preview and watchers let go as the window goes (GraphDock.dispose).
        try:
            self.dock.dispose()
        except Exception:
            pass
        super().closeEvent(event)


_window = [None]


def open_window():
    """The graph editor window (GraphWindow), made or brought forward."""
    from shiboken2 import isValid
    from .node_editor import _modo_window, bring_forward
    window = _window[0]
    if window is None or not isValid(window) or not window.isVisible():
        window = _window[0] = GraphWindow(_modo_window())
        window.show()
    bring_forward(window)
    return window
