"""The compositor's graph editor: the same canvas as the material graph editor, over a finished render's buffers.

A window of its own that does not block Modo. The scene's settings hold the one copy of the graph: every edit here is
written there through the undoable settings command, a moment after it is made, and the preview window then makes the
Composite buffer again from the render it has kept. Nothing here renders.
"""
import copy
import uuid
from PySide2 import QtCore, QtGui, QtWidgets
from . import compositor
from .node_widgets import GraphView, QuickAdd, curve, MENU_STYLE, NODE_BODY, NODE_EDGE, ACCENT, TEXT, TEXT_PORT, TEXT_DIM, GRID

WIDTH, HEADER, ROW = 170, 24, 20
# A node's header and the wire out of it, by what the node is.
HEADERS = {'input': '#35627f', 'merge': '#3d7449', 'sum': '#3d7449', 'grade': '#86682f', 'blur': '#65548a', 'glow': '#65548a', 'output': '#7a3f3f'}
WIRES = {'input': '#77bce8', 'merge': '#89ce94', 'sum': '#89ce94', 'grade': '#e4b367', 'blur': '#c6a0e9', 'glow': '#c6a0e9', 'output': '#e89a9a'}
# The other nodes are coloured by what they are for: colour as Grade is, filters as Blur is, and so on.
FAMILIES = {'colour': ('#86682f', '#e4b367'), 'filter': ('#65548a', '#c6a0e9'), 'matte': ('#59636e', '#c8d2dc'), 'make': ('#35627f', '#77bce8'),
            'note': ('#8a7d3a', '#d8c86a')}
for _kind, _node in compositor.NODES.items():
    if _kind not in HEADERS:
        HEADERS[_kind], WIRES[_kind] = FAMILIES[_node.get('family', 'filter')]
_open = {}


def open_editor(panel):
    """Show the compositor for the scene the preview window is on; one window, brought forward if it is open."""
    from shiboken2 import isValid
    editor = _open.get('editor')
    if editor is not None and isValid(editor) and editor.isVisible():
        editor.raise_(); editor.activateWindow(); return editor
    editor = _open['editor'] = Editor(panel)
    editor.finished.connect(lambda *_: _open.pop('editor', None))
    editor.show(); editor.raise_(); editor.activateWindow()
    return editor


def label(parent, words, color, x, y, width, size=-1):
    item = QtWidgets.QGraphicsSimpleTextItem(parent)
    font = item.font()
    if size:
        font.setPointSizeF(max(6.0, font.pointSizeF() + size))
    item.setFont(font); item.setBrush(QtGui.QColor(color))
    item.setText(QtGui.QFontMetrics(font).elidedText(words, QtCore.Qt.ElideRight, int(width)))
    item.setPos(x, y)
    return item


def rounded(width, height, radius, square_bottom=False):
    path = QtGui.QPainterPath(); path.addRoundedRect(QtCore.QRectF(0, 0, width, height), radius, radius)
    if square_bottom:
        lower = QtGui.QPainterPath(); lower.addRect(QtCore.QRectF(0, height - radius, width, radius)); path = path.united(lower)
    return path


def shown(linear):
    """A linear value as the sRGB a chip and the colour picker show it in, 0 to 1."""
    value = min(max(float(linear), 0.0), 1.0)
    return value * 12.92 if value <= 0.0031308 else 1.055 * value ** (1.0 / 2.4) - 0.055


def linear(shown_value):
    """An sRGB value from the colour picker, as the linear value a node keeps."""
    value = min(max(float(shown_value), 0.0), 1.0)
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


class Swatch(QtWidgets.QGraphicsRectItem):
    """A colour setting shown as a chip on its node, made of Qt's own shapes; a click on it chooses another colour."""
    def __init__(self, editor, identity, key, value, parent):
        super().__init__(parent)
        self.editor, self.identity, self.key = editor, identity, key
        self.setBrush(QtGui.QColor.fromRgbF(*[shown(v) for v in value]))
        self.setPen(QtGui.QPen(QtGui.QColor(NODE_EDGE), 1))
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip('Click to choose the colour')

    def mousePressEvent(self, event):
        # The press is the chip's, so that the node is not moved by it; the colour is chosen when the button comes up.
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()
        if self.rect().contains(event.pos()):
            QtCore.QTimer.singleShot(0, lambda: self.editor.choose_colour(self.identity, self.key))


class Socket(QtWidgets.QGraphicsEllipseItem):
    """Where a wire begins (key None, a node's picture) or ends (one of its inputs)."""
    def __init__(self, editor, identity, key, parent, color):
        super().__init__(-5, -5, 10, 10, parent)
        self.is_socket = True
        self.setCursor(QtCore.Qt.CrossCursor)
        self.editor, self.identity, self.key = editor, identity, key
        self.setBrush(QtGui.QColor(color)); self.setPen(QtGui.QPen(QtGui.QColor(NODE_EDGE), 1.5))
        self.setToolTip('Drag to an input to connect' if key is None else key + ': drag a wire here. Right-click to disconnect.')


class PassChooser(QtWidgets.QDialog):
    """Which passes a built graph takes, each to a Grade of its own; what they leave out of the beauty is the Remainder.
    None is ticked to begin with."""
    def __init__(self, parent, title, intro, options, ticked):
        super().__init__(parent)
        self.setWindowTitle(title)
        # Slim, and no taller than the choices need.
        self.setFixedWidth(300)
        layout = QtWidgets.QVBoxLayout(self)
        words = QtWidgets.QLabel(intro)
        words.setWordWrap(True)
        layout.addWidget(words)
        # A checkbox each, as Modo draws them: a list's own check marks are drawn by Modo's style only when ticked, so
        # with none ticked there was nothing to show that they can be.
        self.boxes = []
        holder = QtWidgets.QWidget()
        rows = QtWidgets.QVBoxLayout(holder)
        for index, (label, name, expression) in enumerate(options):
            box = QtWidgets.QCheckBox(label)
            box.setChecked(index in ticked)
            box.setToolTip('%s: %s' % (name, expression))
            box.toggled.connect(self.check)
            rows.addWidget(box)
            self.boxes.append(box)
        rows.addStretch(1)
        rows.setContentsMargins(4, 4, 4, 4); rows.setSpacing(2)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        scroll.setFixedHeight(min(holder.sizeHint().height() + 4, 280))
        layout.addWidget(scroll)
        row = QtWidgets.QHBoxLayout()
        for label, state in (('Select All', QtCore.Qt.Checked), ('Select None', QtCore.Qt.Unchecked)):
            button = QtWidgets.QPushButton(label)
            button.setAutoDefault(False)
            button.clicked.connect(lambda checked=False, s=state: self.tick_all(s))
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setText('Build')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.check()

    def tick_all(self, state):
        for box in self.boxes:
            box.setChecked(state == QtCore.Qt.Checked)

    def chosen(self):
        return [index for index, box in enumerate(self.boxes) if box.isChecked()]

    def check(self, *args):
        # A graph needs a pass at least.
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(bool(self.chosen()))


def choose(parent, title, intro, options, ticked):
    """Ask which of the options to build from: the indices chosen, or None."""
    dialog = PassChooser(parent, title, intro, options, ticked)
    if dialog.exec_() != QtWidgets.QDialog.Accepted:
        return None
    return dialog.chosen()


class Node(QtWidgets.QGraphicsRectItem):
    """A node, made of Qt's own shapes; the item itself paints nothing."""
    def __init__(self, editor, identity, value):
        kind = value['type']; schema = compositor.NODES[kind]
        ports = compositor.ports(value)
        held = compositor.parameters(value)
        # A note is its words.
        words = held.get('text', '').splitlines() or ['(empty note)'] if kind == 'note' else []
        height = HEADER + (len(words) * ROW if kind == 'note' else max(1, len(ports)) * ROW) + 8
        super().__init__(0, 0, WIDTH, height)
        self.editor, self.identity = editor, identity
        self.setFlags(self.ItemIsMovable | self.ItemIsSelectable | self.ItemSendsGeometryChanges | self.ItemHasNoContents)
        self.body = QtWidgets.QGraphicsPathItem(rounded(WIDTH, height, 6), self)
        self.body.setBrush(QtGui.QColor(NODE_BODY)); self.body.setPen(QtGui.QPen(QtGui.QColor(NODE_EDGE), 1))
        header = QtWidgets.QGraphicsPathItem(rounded(WIDTH, HEADER, 6, square_bottom=True), self)
        header.setBrush(QtGui.QColor(HEADERS[kind])); header.setPen(QtGui.QPen(QtCore.Qt.NoPen))
        title = schema['label']
        if kind == 'input':
            title = editor.buffer_label(held['buffer'])
        elif kind == 'merge':
            title = 'Merge: ' + held['mode']
        elif kind == 'cryptomatte':
            title = 'Cryptomatte: ' + (('ID ' + held['matte'][1:]) if held['matte'].startswith('#') else held['matte'] or '(choose)')
        label(self, title, TEXT, 10, 4, WIDTH - 20).setToolTip(schema['tip'])
        self.sockets = {}
        if kind == 'note':
            for index, line in enumerate(words):
                label(self, line, TEXT, 10, HEADER + 4 + index * ROW, WIDTH - 20, size=-1)
            self.setPos(*value.get('position', [0, 0]))
            return
        if kind != 'output':
            self.sockets[None] = Socket(editor, identity, None, self, WIRES[kind]); self.sockets[None].setPos(WIDTH, HEADER / 2)
        wired = value.get('inputs') or {}
        for index, key in enumerate(ports):
            y = HEADER + 4 + index * ROW
            label(self, compositor.port_label(key), TEXT if key in wired else TEXT_PORT, 12, y + 2, WIDTH - 22, size=-1)
            socket = Socket(editor, identity, key, self, '#9aa3ad'); socket.setPos(0, y + ROW / 2); self.sockets[key] = socket
        if kind == 'constant':
            # The colour itself, to be clicked to choose another.
            chip = Swatch(editor, identity, 'color', held['color'], self)
            chip.setRect(12, HEADER + 5, WIDTH - 24, ROW - 4)
        elif not ports:
            label(self, 'a matte from the %s Cryptomatte' % held['category'] if kind == 'cryptomatte' else 'a buffer of the render',
                  TEXT_DIM, 12, HEADER + 6, WIDTH - 22, size=-1)
        self.setPos(*value.get('position', [0, 0]))

    def itemChange(self, change, value):
        if change == self.ItemPositionHasChanged and hasattr(self, 'identity') and not self.editor.busy:
            self.editor.graph['nodes'][self.identity]['position'] = [self.pos().x(), self.pos().y()]
            self.editor.edges()
        elif change == self.ItemSelectedHasChanged and hasattr(self, 'body'):
            self.body.setPen(QtGui.QPen(QtGui.QColor(ACCENT), 2) if value else QtGui.QPen(QtGui.QColor(NODE_EDGE), 1))
            self.setZValue(1 if value else 0)
        return super().itemChange(change, value)


class View(GraphView):
    """The material editor's canvas, with the compositor's own menu."""
    def contextMenuEvent(self, event):
        socket = self.socket_at(event.pos()); item = self.itemAt(event.pos())
        owner = self.node_at(event.pos())
        identity = getattr(owner, 'identity', None)
        menu = QtWidgets.QMenu(self); menu.setStyleSheet(MENU_STYLE); connection = None

        def entry(words, what, enabled=True):
            action = QtWidgets.QAction(words, menu); action.setData(what); action.setEnabled(enabled); menu.addAction(action)
        if socket and socket.key is not None:
            connection = (socket.identity, socket.key); entry('Disconnect ' + socket.key, 'disconnect')
        elif item and getattr(item, 'connection', None):
            connection = item.connection; entry('Disconnect', 'disconnect')
        if identity in self.editor.graph['nodes']:
            if owner is not None and not owner.isSelected():
                self.scene().clearSelection(); owner.setSelected(True)
            if connection:
                menu.addSeparator()
            entry('Duplicate\tCtrl+D', 'duplicate', identity != self.editor.graph['root'])
            if self.editor.probing:
                entry('Note Probed Values', 'note_probe', self.editor.probe_point is not None)
            entry('Delete\tDel', 'delete', identity != self.editor.graph['root'])
        if not menu.isEmpty():
            menu.addSeparator()
        # A buffer of the render as a node where the click was; on an input, wired into it.
        target = (socket.identity, socket.key) if socket and socket.key is not None else None
        aovs = QtWidgets.QMenu('Add Input AOV', menu)
        menu.addMenu(aovs)
        self.editor.aov_menu(aovs)
        entry('Add Node...\tTab', 'add'); entry('Frame Selected\tF', 'frame'); entry('Frame All\tA', 'frame_all')
        chosen = menu.exec_(event.globalPos())
        what = chosen.data() if chosen is not None else None
        if isinstance(what, tuple):
            self.editor.add_aov(what, self.mapToScene(event.pos()), target)
            return
        if what == 'disconnect': self.editor.unlink(*connection)
        elif what == 'duplicate': self.editor.duplicate()
        elif what == 'note_probe': self.editor.note_at(self.editor.probe_point)
        elif what == 'delete': self.editor.remove()
        elif what == 'add': self.editor.quick_add(self.mapToScene(event.pos()), event.globalPos())
        elif what == 'frame': self.editor.frame()
        elif what == 'frame_all': self.editor.frame(everything=True)


class Editor(QtWidgets.QDialog):
    def __init__(self, panel):
        super().__init__(QtWidgets.QApplication.activeWindow())
        self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowSystemMenuHint | QtCore.Qt.WindowMinMaxButtonsHint | QtCore.Qt.WindowCloseButtonHint)
        self.setModal(False); self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setMinimumSize(760, 460); self.resize(1100, 640)
        self.setWindowTitle('MoonRay Compositor')
        self.panel = panel
        self.graph = self.stored() or compositor.new()
        self.pending = None; self.items = {}; self.links = []; self.busy = False; self.expanded = set()
        self.undo_states = []; self.redo_states = []; self.fields = []
        layout = QtWidgets.QVBoxLayout(self); layout.setContentsMargins(6, 6, 6, 6); layout.setSpacing(4)
        toolbar = QtWidgets.QHBoxLayout(); toolbar.setSpacing(4); layout.addLayout(toolbar)
        self.menus = []

        def menu_button(title, actions):
            button = QtWidgets.QToolButton(); button.setText(title); button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            button.setMinimumWidth(button.fontMetrics().horizontalAdvance(title) + 36)
            menu = QtWidgets.QMenu(button); menu.setStyleSheet(MENU_STYLE); self.menus.append(menu)
            for words, callback in actions:
                if words is None: menu.addSeparator()
                else: menu.addAction(words, callback)
            button.setMenu(menu); toolbar.addWidget(button)
        menu_button('Add', [(compositor.NODES[kind]['label'], lambda kind=kind: self.add(kind)) for kind in compositor.NODES if kind != 'output'])
        menu_button('Node', [('Duplicate\tCtrl+D', self.duplicate), ('Delete\tDel', self.remove)])
        menu_button('Build', [('From Light Passes', lambda: self.build('passes')), ('From Light Groups', lambda: self.build('groups'))])
        # Probe mode: each node's value at the pixel under the pointer in the preview, and notes of those values.
        self.probe_button = QtWidgets.QToolButton(); self.probe_button.setText('Probe'); self.probe_button.setCheckable(True); self.probe_button.setAutoRaise(True)
        self.probe_button.setToolTip('Over the preview picture, a tooltip at the pointer gives what each node makes at that pixel. '
                                     'Right-click there for a note that keeps those values and follows the graph and the render.')
        self.probe_button.toggled.connect(self.set_probing); toolbar.addWidget(self.probe_button)
        self.note_button = QtWidgets.QToolButton(); self.note_button.setText('Note Values'); self.note_button.setAutoRaise(True); self.note_button.setEnabled(False)
        self.note_button.setToolTip('A probe note of the values at the last pixel probed, as a right-click on the preview makes')
        self.note_button.clicked.connect(lambda: self.note_at(self.probe_point)); toolbar.addWidget(self.note_button)
        # Probe notes follow the graph and the render: looked at once a second, and worked out again when either changed.
        self.notes_timer = QtCore.QTimer(self); self.notes_timer.setInterval(1000); self.notes_timer.timeout.connect(self.refresh_notes)
        self.notes_seen = None; self.notes_timer.start()
        self.probing = False; self.probe_point = None; self.probed = {}
        self.probe_timer = QtCore.QTimer(self); self.probe_timer.setSingleShot(True); self.probe_timer.setInterval(120)
        self.probe_timer.timeout.connect(self.update_probe)
        menu_button('View', [('Frame Selected\tF', self.frame), ('Frame All\tA', lambda: self.frame(everything=True))])
        for words, tip, callback in [('Undo', 'Ctrl+Z', self.undo), ('Redo', 'Ctrl+Y', self.redo)]:
            button = QtWidgets.QToolButton(); button.setText(words); button.setToolTip(tip); button.setAutoRaise(True); button.clicked.connect(callback); toolbar.addWidget(button)
        toolbar.addStretch(1)
        show = QtWidgets.QToolButton(); show.setText('Show Composite'); show.setAutoRaise(True)
        show.setToolTip('Choose the Composite buffer in the preview window'); show.clicked.connect(self.show_composite); toolbar.addWidget(show)
        clear = QtWidgets.QToolButton(); clear.setText('Clear Graph'); clear.setAutoRaise(True)
        clear.setToolTip('Back to the beauty wired straight to the output, which makes no Composite buffer'); clear.clicked.connect(self.clear); toolbar.addWidget(clear)
        splitter = QtWidgets.QSplitter(); layout.addWidget(splitter, 1)
        self.build_library(splitter)
        self.canvas = QtWidgets.QGraphicsScene(self); self.view = View(self, self.canvas); splitter.addWidget(self.view)
        pane = QtWidgets.QWidget(); right = QtWidgets.QVBoxLayout(pane); right.setContentsMargins(6, 0, 0, 0); right.setSpacing(6); splitter.addWidget(pane)
        splitter.setSizes([200, 620, 280]); splitter.setStretchFactor(1, 1)
        self.property_title = QtWidgets.QLabel('Properties'); font = self.property_title.font(); font.setBold(True); self.property_title.setFont(font); right.addWidget(self.property_title)
        self.property_help = QtWidgets.QLabel(''); self.property_help.setWordWrap(True); self.property_help.setEnabled(False); right.addWidget(self.property_help)
        self.form_host = QtWidgets.QWidget(); self.form = QtWidgets.QFormLayout(self.form_host); self.form.setContentsMargins(0, 0, 0, 0); right.addWidget(self.form_host)
        right.addStretch(1)
        footer = QtWidgets.QHBoxLayout(); layout.addLayout(footer)
        self.info = QtWidgets.QLabel('Tab or double-click adds a node. Drag between sockets to connect. The Composite buffer is made when a MoonRay render has finished.')
        self.info.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.info.setToolTip('Wheel zooms. Middle drag, or Alt and drag, pans. F frames the selection, A everything. Ctrl+D duplicates, Delete removes, Ctrl+Z undoes. Right-click a socket or wire to disconnect.')
        footer.addWidget(self.info, 1)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close); footer.addWidget(buttons)
        buttons.rejected.connect(self.reject)
        self.canvas.selectionChanged.connect(self.inspect)
        for button in self.findChildren(QtWidgets.QPushButton):
            button.setAutoDefault(False); button.setDefault(False)
        # An edit is written to the scene a moment after it is made, so that dragging a number is one write.
        self.write_timer = QtCore.QTimer(self); self.write_timer.setSingleShot(True); self.write_timer.setInterval(250)
        self.write_timer.timeout.connect(self.write)
        # And the scene is looked at for a graph changed elsewhere: by Modo's undo, or by another scene coming up.
        self.watch_timer = QtCore.QTimer(self); self.watch_timer.setInterval(700); self.watch_timer.timeout.connect(self.watch); self.watch_timer.start()
        try:
            panel.renderer.buffers.notice.connect(self.heard)
        except Exception:
            pass
        self.finished.connect(lambda *_: self.closing())
        self.rebuild(); self.frame(everything=True)

    # ---- the nodes there are to add, down the left as in the material graph editor ----
    def build_library(self, splitter):
        pane = self.library = QtWidgets.QWidget(); layout = QtWidgets.QVBoxLayout(pane); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(4)
        self.node_search = QtWidgets.QLineEdit(); self.node_search.setClearButtonEnabled(True); self.node_search.setPlaceholderText('Search nodes'); layout.addWidget(self.node_search)
        self.node_tree = QtWidgets.QTreeWidget(); self.node_tree.setHeaderHidden(True); self.node_tree.setIndentation(12); layout.addWidget(self.node_tree, 1)
        self.node_tree.setToolTip('Click a node to add it. With a node selected, the new one goes after it.')
        self.node_tree.itemClicked.connect(self.add_from_library)
        self.node_search.textChanged.connect(self.filter_library)
        self.fill_library()
        splitter.addWidget(pane)

    def fill_library(self):
        """The render's buffers, each a node that takes it, and then the nodes that work on pictures."""
        self.node_tree.clear()

        def group(words, open_=True):
            item = QtWidgets.QTreeWidgetItem(self.node_tree, [words]); item.setExpanded(open_); return item

        def row(parent, words, kind, values, tip):
            item = QtWidgets.QTreeWidgetItem(parent, [words]); item.setData(0, QtCore.Qt.UserRole, [kind, values]); item.setToolTip(0, tip)
        buffers = group('Buffers of the render')
        for words, key in self.buffer_choices():
            row(buffers, words, 'input', {'buffer': key}, 'The render\'s %s buffer.' % words)
        merges = group('Merge')
        for mode in compositor.MODES:
            row(merges, 'Merge: ' + mode, 'merge', {'mode': mode}, compositor.NODES['merge']['tip'])
        row(merges, 'Sum', 'sum', {}, compositor.NODES['sum']['tip'])
        def family(name):
            return [kind for kind, node in compositor.NODES.items() if node.get('family') == name]
        colour = group('Colour')
        for kind in ['grade'] + family('colour'):
            row(colour, compositor.NODES[kind]['label'], kind, {}, compositor.NODES[kind]['tip'])
        filters = group('Filters')
        for kind in ['blur', 'glow'] + family('filter'):
            row(filters, compositor.NODES[kind]['label'], kind, {}, compositor.NODES[kind]['tip'])
        mattes = group('Mattes')
        for kind in family('matte'):
            row(mattes, compositor.NODES[kind]['label'], kind, {}, compositor.NODES[kind]['tip'])
        makes = group('Make')
        for kind in family('make'):
            row(makes, compositor.NODES[kind]['label'], kind, {}, compositor.NODES[kind]['tip'])
        self.library_listed = self.buffer_choices()
        self.filter_library(self.node_search.text())

    def filter_library(self, text):
        query = text.casefold().strip()
        for index in range(self.node_tree.topLevelItemCount()):
            group = self.node_tree.topLevelItem(index); visible = False
            for child in range(group.childCount()):
                row = group.child(child); match = query in (group.text(0) + ' ' + row.text(0)).casefold()
                row.setHidden(not match); visible = visible or match
            group.setHidden(not visible)
            if query and visible:
                group.setExpanded(True)

    def add_from_library(self, item, column):
        held = item.data(0, QtCore.Qt.UserRole)
        if not held:
            return
        self.add(held[0], values=dict(held[1]))

    # ---- the scene's copy of the graph ----
    def stored(self):
        try:
            held = self.panel._settings_values_stored().get('compositor')
            return compositor.validate(held) if held else None
        except Exception:
            return None

    def changed(self):
        """An edit has been made: redraw what it touches, and write it to the scene shortly."""
        self.write_timer.start()

    def write(self):
        try:
            graph = compositor.validate(self.graph)
        except ValueError as exc:
            self.info.setText(str(exc)); return
        # A graph that does nothing is not kept: the scene then has no Composite buffer. One with notes on it is kept for
        # them, and still makes no Composite (compositor.trivial).
        held = {} if compositor.trivial(graph) and not any(node['type'] == 'note' for node in graph['nodes'].values()) else graph
        if (self.stored() or {}) == held:
            return
        if self.panel._store(compositor=held):
            self.info.setText('The Composite buffer is not made: the graph does nothing yet.' if not held
                              else 'Written to the scene. The Composite buffer is made from the render that is kept.')

    def held_by_hand(self):
        """Whether a node is being moved, or the mouse button is down on the canvas: the graph is not read again then,
        or a node held for longer than the scene is looked at was put back where the scene last had it."""
        return (getattr(self.view, 'move_before', None) is not None or self.view.start_socket is not None
                or QtWidgets.QApplication.mouseButtons() != QtCore.Qt.NoButton)

    def watch(self):
        if getattr(self, 'library_listed', None) != self.buffer_choices():
            self.fill_library()
        if self.write_timer.isActive() or self.busy or self.held_by_hand():
            return
        held = self.stored()
        if held is None:
            return
        try:
            mine = compositor.validate(self.graph)
        except ValueError:
            return
        if held != mine:
            self.graph = held; self.rebuild()

    def heard(self, words):
        if 'omposit' in str(words):
            self.info.setText(str(words))

    def closing(self):
        self.watch_timer.stop()
        if self.probing:
            self.set_probing(False)
        if self.write_timer.isActive():
            self.write_timer.stop(); self.write()
        try:
            self.panel.renderer.buffers.notice.disconnect(self.heard)
        except Exception:
            pass

    def build(self, kind):
        """Lay out a graph that puts the render back together from its passes ('passes': diffuse, glossy, reflection
        and the rest) or from its light groups ('groups'), each pass with a Grade of its own; the outputs it needs are
        added to the scene where it lacks them, to be filled by the next render."""
        values = self.panel._settings_values()
        if kind == 'passes':
            # MoonRay's light passes, which together make the beauty, and the scene's own light path outputs, to take as
            # passes too. None is ticked: what is worked on is chosen.
            wanted = list(compositor.PASSES)
            wanted += [(name + '  (in the scene)', name, expression) for words, name, expression in compositor.scene_passes(values.get('custom_aovs'), wanted)]
        else:
            groups = compositor.light_groups(values.get('production'), self.moonray_lights())
            if len(groups) == 1:
                asked = QtWidgets.QMessageBox.question(self, 'Build from light groups', 'No light has a light-group label yet, so '
                                                       'only the environment\'s light is a group of its own. Give lights labels in the '
                                                       'Lighting scene controls (or a MoonRay light\'s Label) for a group each. Build anyway?',
                                                       QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel)
                if asked != QtWidgets.QMessageBox.Ok:
                    return
            wanted = [(words, ('environment' if label == compositor.ENVIRONMENT_LABEL else label) + '_light', compositor.light_group_expression(label))
                      for words, label in groups]
        title = 'Build from Light Passes' if kind == 'passes' else 'Build from Light Groups'
        intro = ('Choose the passes to work on, each with a Grade of its own. A pass not chosen stays in the Remainder.' if kind == 'passes'
                 else 'Choose the light groups to work on, each with a Grade of its own. A group not chosen stays in the Remainder.')
        picked = choose(self, title, intro, wanted, set())
        if picked is None:
            return
        wanted = [wanted[index] for index in picked]
        if not compositor.trivial(self.graph):
            asked = QtWidgets.QMessageBox.question(self, 'Build the compositor graph', 'This replaces the graph that is there now. '
                                                   'Undo brings it back.', QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel)
            if asked != QtWidgets.QMessageBox.Ok:
                return
        entries, names = compositor.pass_outputs(values.get('custom_aovs'), wanted)
        if entries != list(values.get('custom_aovs') or []):
            if not self.panel._store(custom_aovs=entries):
                return
            self.panel._sync_output_menu(entries, self.panel._display_filter_buffers())
        before = copy.deepcopy(self.graph)
        self.graph = compositor.pass_graph(list(zip(names, [words for words, name, expression in wanted])))
        self.rebuild(); self.remember(before); self.frame(everything=True)
        missing = [name for name in names if name not in {key for words, key in self.buffer_choices()}]
        self.info.setText('Built from %d %s and the Remainder. ' % (len(names), 'passes' if kind == 'passes' else 'light groups')
                          + ('Render to fill the new passes; the Composite is made when the render finishes.' if missing
                             else 'With every Grade left alone the Composite is the beauty.'))

    def moonray_lights(self):
        """The MoonRay light items in the scene, for their light-group labels."""
        try:
            import modo
            from . import entities
            return [entity for entity in entities.collect(modo.Scene(), [])
                    if entities.catalog()[entity['class']]['category'] == 'light']
        except Exception:
            return []

    # ---- probe mode ----
    def set_probing(self, on):
        """Probe mode on or off: on, the preview's pointer gives the pixel each node's value is shown at."""
        self.probing = bool(on)
        self.note_button.setEnabled(self.probing)
        try:
            if self.probing:
                self.panel.preview.hovered.connect(self.probe_hovered)
            else:
                self.panel.preview.hovered.disconnect(self.probe_hovered)
        except (RuntimeError, TypeError):
            pass
        if not self.probing:
            self.probed = {}
            QtWidgets.QToolTip.hideText()
        else:
            self.info.setText('Probe: hold the pointer over the picture in the preview window for its values. Right-click there '
                              'for a note of them.')

    def probe_hovered(self, x, y):
        # Off the picture the tooltip goes; the last point is kept for Note Values.
        if x < 0 or y < 0:
            self.probe_timer.stop(); QtWidgets.QToolTip.hideText()
            return
        self.probe_point = (x, y)
        self.probe_timer.start()

    def sampled_at(self, x, y):
        """Each node's value at a pixel of the finished render, {node: (r, g, b) or None}; None with no render to read."""
        from . import compositor_probe
        frame = getattr(self.panel.renderer.buffers, 'frame', None) or {}
        size = compositor_probe.size(frame) if frame else None
        if size is None:
            return None
        try:
            return compositor.sample(self.graph, lambda key: compositor_probe.value(frame, key, x, y), x, y, size[0], size[1])
        except (ValueError, OSError):
            return None

    def node_words(self, identity):
        node = self.graph['nodes'][identity]
        if node['type'] == 'input':
            return self.buffer_label(compositor.parameters(node)['buffer'])
        return compositor.NODES[node['type']]['label']

    def probe_text(self, sampled, x, y):
        """The values at a pixel, node by node in the order the graph makes them, as the tooltip and a probe note say them."""
        if sampled is None:
            return 'Probe at %d, %d\nNo finished render to read values from.' % (x, y)
        try:
            made = [identity for identity in compositor.order(compositor.validate(self.graph)) if identity in sampled]
        except ValueError:
            made = list(sampled)
        return compositor.probe_note([(self.node_words(identity), sampled[identity]) for identity in made], x, y)

    def update_probe(self):
        """The tooltip at the pointer: what each node makes at the pixel under it."""
        if not self.probing or self.probe_point is None:
            return
        x, y = self.probe_point
        sampled = self.sampled_at(x, y)
        self.probed = sampled or {}
        QtWidgets.QToolTip.showText(QtGui.QCursor.pos(), self.probe_text(sampled, x, y), self.panel.preview)

    def note_at(self, point):
        """A probe note of the values at a pixel, beside the Composite: it keeps the pixel and follows the graph and the
        render (refresh_notes)."""
        if point is None:
            self.info.setText('Probe a pixel first: switch Probe on and hold the pointer over the preview picture.'); return
        x, y = point
        placed = [node['position'] for node in self.graph['nodes'].values()] or [[0.0, 0.0]]
        right = max(position[0] for position in placed) + WIDTH + 60
        top = min(position[1] for position in placed)
        before = copy.deepcopy(self.graph)
        identity = 'note_' + uuid.uuid4().hex[:6]
        self.graph['nodes'][identity] = {'type': 'note', 'inputs': {}, 'position': self.free_place(right, top),
                                         'parameters': {'text': self.probe_text(self.sampled_at(x, y), x, y), 'probe_x': float(x), 'probe_y': float(y)}}
        self.rebuild(); self.remember(before)
        self.info.setText('A probe note of the values at %d, %d. It follows the graph and the render.' % (x, y))

    def refresh_notes(self):
        """Work the probe notes' words out again when the graph or the render has changed since they were."""
        if self.busy or self.held_by_hand() or not any(node['type'] == 'note' and compositor.parameters(node)['probe_x'] >= 0
                                                       for node in self.graph['nodes'].values()):
            return
        import json
        frame = getattr(self.panel.renderer.buffers, 'frame', None) or {}
        shape = {identity: dict(node, parameters={k: v for k, v in (node.get('parameters') or {}).items() if k != 'text'}, position=None)
                 for identity, node in self.graph['nodes'].items()}
        seen = (id(frame), json.dumps(shape, sort_keys=True, default=str))
        if seen == self.notes_seen:
            return
        self.notes_seen = seen
        changed = False
        for node in self.graph['nodes'].values():
            held = compositor.parameters(node) if node['type'] == 'note' else None
            if held is None or held['probe_x'] < 0 or held['probe_y'] < 0:
                continue
            x, y = int(held['probe_x']), int(held['probe_y'])
            text = self.probe_text(self.sampled_at(x, y), x, y)
            if text != held['text']:
                node.setdefault('parameters', {})['text'] = text; changed = True
        if changed:
            selected = self.selected_nodes()
            self.rebuild()
            for identity in selected:
                if identity in self.items:
                    self.items[identity].setSelected(True)
            self.write_timer.start()

    def aov_menu(self, menu):
        """Fill the Add Input AOV menu: the render's buffers, then the light passes and light groups the scene does not
        have yet, and a light path expression of one's own. A buffer the graph has a Buffer node for already is not
        offered again. Each action's data says what it adds."""
        menu.setStyleSheet(MENU_STYLE)
        values = self.panel._settings_values()
        present = {compositor.parameters(node).get('buffer') for node in self.graph['nodes'].values() if node.get('type') == 'input'}
        listed = [(words, key) for words, key in self.buffer_choices() if key not in present]
        for words, key in listed:
            menu.addAction(words).setData(('buffer', key))
        have = {entry.get('expression', '').strip() for entry in values.get('custom_aovs') or [] if entry.get('kind') == 'lpe'}
        passes = [(words, name, expression) for words, name, expression in compositor.PASSES if expression not in have and name not in present]
        groups = [(words, ('environment' if label == compositor.ENVIRONMENT_LABEL else label) + '_light', compositor.light_group_expression(label))
                  for words, label in compositor.light_groups(values.get('production'), self.moonray_lights())]
        groups = [group for group in groups if group[2] not in have and group[1] not in present]
        if listed:
            menu.addSeparator()
        # Each submenu is made with its parent menu as its owner and kept on it, so that Python does not let it go.
        menu.held = []
        for title, offered in (('Light Pass', passes), ('Light Group', groups)):
            sub = QtWidgets.QMenu(title, menu)
            menu.addMenu(sub)
            menu.held.append(sub)
            sub.setStyleSheet(MENU_STYLE)
            sub.setToolTipsVisible(True)
            for words, name, expression in offered:
                action = sub.addAction(words)
                action.setData(('new', words, name, expression))
                action.setToolTip('Added to the render\'s outputs as %s (%s); filled by the next render.' % (name, expression))
            sub.setEnabled(bool(offered))
        menu.addAction('New Light Path Expression...').setData(('ask',))

    def add_aov(self, what, point, target=None):
        """Add a Buffer node for what the Add Input AOV menu chose, at point, wired into target (node, input) where
        given. A pass the render has no output for is added to the scene's outputs first, to be filled by the next
        render."""
        if what[0] == 'ask':
            from . import outputs
            name, ok = QtWidgets.QInputDialog.getText(self, 'New Light Path Expression', 'Name of the output (letters, numbers and _)')
            if not ok or not name.strip():
                return
            expression, ok = QtWidgets.QInputDialog.getText(self, 'New Light Path Expression', 'Light path expression, such as C<RD>[<L.>O]')
            if not ok or not expression.strip():
                return
            problem = outputs.lpe_problem(expression.strip())
            if problem:
                QtWidgets.QMessageBox.warning(self, 'New Light Path Expression', problem)
                return
            what = ('new', name.strip(), name.strip(), expression.strip())
        if what[0] == 'new':
            values = self.panel._settings_values()
            entries, names = compositor.pass_outputs(values.get('custom_aovs'), [what[1:]])
            if entries != list(values.get('custom_aovs') or []):
                try:
                    from . import outputs
                    outputs.values(entries)
                except ValueError as exc:
                    QtWidgets.QMessageBox.warning(self, 'Add Input AOV', str(exc))
                    return
                if not self.panel._store(custom_aovs=entries):
                    return
                self.panel._sync_output_menu(entries, self.panel._display_filter_buffers())
                self.info.setText('%s is added to the render\'s outputs; the next render fills it.' % names[0])
            key = names[0]
        else:
            key = what[1]
        self.add('input', point, target, {'buffer': key})

    def choose_colour(self, identity, key):
        """The colour picker for a colour setting of a node, from a click on its chip: what is chosen is kept linear."""
        node = self.graph['nodes'].get(identity)
        if node is None:
            return
        held = compositor.parameters(node)[key]
        picked = QtWidgets.QColorDialog.getColor(QtGui.QColor.fromRgbF(*[shown(v) for v in held]), self, 'Colour')
        if not picked.isValid():
            return
        self.set_value(identity, key, [round(linear(v), 6) for v in (picked.redF(), picked.greenF(), picked.blueF())], redraw=True)
        if self.selected() == identity:
            self.inspect()

    def matte_choices(self, category):
        """The mattes given in the scene's Cryptomatte tabs, [(words, value)]: each name, and each ID as #number."""
        names, numbers = set(), set()
        try:
            import json
            import modo
            from . import properties
            scene = modo.Scene()
            if category == 'material':
                items = [item for item in scene.items('advancedMaterial', superType=True)]
            else:
                items = list(scene.items('locator', superType=True))
            for item in items:
                try:
                    held = json.loads(item.readTag(properties.TAG))
                except (LookupError, RuntimeError, ValueError, TypeError):
                    continue
                if not isinstance(held, dict):
                    continue
                if str(held.get('crypto_name') or '').strip():
                    names.add(str(held['crypto_name']).strip())
                if int(held.get('crypto_id') or 0) > 0:
                    numbers.add(int(held['crypto_id']))
        except Exception:
            pass
        return [(name, name) for name in sorted(names, key=str.casefold)] + [('ID %d' % number, '#%d' % number) for number in sorted(numbers)]

    # ---- what the canvas asks of its editor ----
    def buffer_label(self, key):
        index = self.panel.buffer.findData(key)
        return self.panel.buffer.itemText(index) if index >= 0 else key

    def buffer_choices(self):
        """The buffers a node can take: those the preview window lists, less the composite itself and the mattes
        that are not pictures."""
        found = []
        for index in range(self.panel.buffer.count()):
            key, words = self.panel.buffer.itemData(index), self.panel.buffer.itemText(index)
            if key and key != 'composite' and not words.startswith('Cryptomatte'):
                found.append((words, key))
        return found

    def selected(self):
        return next((item.identity for item in self.canvas.selectedItems() if isinstance(item, Node)), None)

    def selected_nodes(self):
        return [item.identity for item in self.canvas.selectedItems() if isinstance(item, Node)]

    def rebuild(self, *args):
        selected = self.selected()
        if hasattr(self, 'view'):
            self.view.cancel_wire()
        self.busy = True; self.pending = None; self.items = {}; self.links = []; self.canvas.clear()
        for identity, value in self.graph['nodes'].items():
            item = Node(self, identity, value); self.items[identity] = item; self.canvas.addItem(item)
        self.edges(); self.busy = False
        if selected in self.items:
            self.items[selected].setSelected(True)
        self.canvas.setSceneRect(self.canvas.itemsBoundingRect().adjusted(-3000, -3000, 3000, 3000)); self.inspect()

    def edges(self):
        if not hasattr(self, 'canvas'):
            return
        for item in self.links:
            if item.scene():
                self.canvas.removeItem(item)
        self.links = []
        for identity, node in self.graph['nodes'].items():
            if identity not in self.items:
                continue
            for key, source in (node.get('inputs') or {}).items():
                if source not in self.items or key not in self.items[identity].sockets:
                    continue
                a = self.items[source].sockets[None].scenePos(); b = self.items[identity].sockets[key].scenePos()
                pen = QtGui.QPen(QtGui.QColor(WIRES[self.graph['nodes'][source]['type']]), 2); pen.setCapStyle(QtCore.Qt.RoundCap)
                edge = self.canvas.addPath(curve(a, b), pen); edge.setZValue(-1); edge.connection = (identity, key)
                edge.setToolTip('Right-click to disconnect ' + key); self.links.append(edge)

    def remember(self, before):
        if before != self.graph:
            self.undo_states.append(before); self.undo_states = self.undo_states[-50:]; self.redo_states = []
            self.changed()

    def undo(self):
        if self.undo_states:
            self.redo_states.append(copy.deepcopy(self.graph)); self.graph = self.undo_states.pop(); self.rebuild(); self.changed()

    def redo(self):
        if self.redo_states:
            self.undo_states.append(copy.deepcopy(self.graph)); self.graph = self.redo_states.pop(); self.rebuild(); self.changed()

    def frame(self, everything=False):
        if not self.items:
            return
        chosen = [] if everything else [self.items[identity] for identity in self.selected_nodes() if identity in self.items]
        bounds = QtCore.QRectF()
        for item in chosen or self.items.values():
            bounds = bounds.united(item.sceneBoundingRect())
        self.view.fitInView(bounds.adjusted(-60, -60, 60, 60), QtCore.Qt.KeepAspectRatio)
        scale = self.view.transform().m11()
        if scale > 1.0:
            self.view.scale(1.0 / scale, 1.0 / scale)

    def snap_selected(self):
        for item in self.canvas.selectedItems():
            if isinstance(item, Node):
                item.setPos(round(item.pos().x() / GRID) * GRID, round(item.pos().y() / GRID) * GRID)

    def toggle_expanded(self, identity):
        pass

    def output(self, identity=None):
        pass

    def focus_socket(self, identity, key):
        item = self.items.get(identity)
        if item is not None and not item.isSelected():
            self.canvas.clearSelection(); item.setSelected(True)

    def socket(self, identity, key):
        """A click on a socket: the first click takes one end of a wire, the second the other."""
        if self.pending is None:
            self.pending = (identity, key); self.info.setText('Now click the socket to connect it to, or Esc.'); return
        first, self.pending = self.pending, None
        ends = [first, (identity, key)]
        source = next((end for end in ends if end[1] is None), None); target = next((end for end in ends if end[1] is not None), None)
        if source and target:
            self.connect_nodes(source[0], target[0], target[1])
        else:
            self.info.setText('A wire runs from a node\'s picture, on its right, to an input, on the left of another.')

    def can_connect(self, source, identity, key):
        if source == identity or source not in self.graph['nodes'] or identity not in self.graph['nodes']:
            return False
        trial = copy.deepcopy(self.graph); trial['nodes'][identity].setdefault('inputs', {})[key] = source
        try:
            compositor.validate(trial); return True
        except ValueError:
            return False

    def connect_nodes(self, source, identity, key):
        if not self.can_connect(source, identity, key):
            self.info.setText('That would feed a node from itself.' if source != identity else 'A node cannot take its own picture.'); return
        before = copy.deepcopy(self.graph)
        self.graph['nodes'][identity].setdefault('inputs', {})[key] = source
        self.rebuild(); self.remember(before)

    def unlink(self, identity, key):
        before = copy.deepcopy(self.graph)
        (self.graph['nodes'][identity].get('inputs') or {}).pop(key, None)
        self.rebuild(); self.remember(before)

    def quick_add(self, scene_point=None, global_point=None, connect=None):
        if scene_point is None:
            centre = self.view.viewport().rect().center(); scene_point = self.view.mapToScene(centre); global_point = self.view.viewport().mapToGlobal(centre)
        names = {compositor.NODES[kind]['label']: kind for kind in compositor.NODES if kind != 'output'}

        def chosen(words):
            self.add(names[words], scene_point, connect)
        tips = {words: compositor.NODES[kind].get('tip', '') for words, kind in names.items()}
        self.popup = QuickAdd(self, list(names), chosen, tips); self.popup.open_at(global_point)

    def consumers(self, identity):
        """The inputs that take a node's picture: [(node, input)]."""
        return [(other, key) for other, node in self.graph['nodes'].items() for key, source in (node.get('inputs') or {}).items() if source == identity]

    def make_room(self, identity):
        """Move what a node feeds, and what that feeds, far enough right not to lie under it."""
        seen, queue = set(), [identity]
        while queue:
            current = queue.pop()
            x = self.graph['nodes'][current]['position'][0]
            for other, _ in self.consumers(current):
                if other in seen:
                    continue
                seen.add(other); queue.append(other)
                place = self.graph['nodes'][other]['position']
                if place[0] < x + WIDTH + 60:
                    place[0] = x + WIDTH + 60

    def free_place(self, x, y):
        """A place at or below this one that no node is standing on."""
        def taken(px, py):
            return any(abs(node['position'][0] - px) < WIDTH + 20 and abs(node['position'][1] - py) < 80 for node in self.graph['nodes'].values())
        while taken(x, y):
            y += 100
        return [x, y]

    def add(self, kind, point=None, connect=None, values=None):
        before = copy.deepcopy(self.graph)
        settings = dict(compositor.parameters({'type': kind}), **(values or {}))
        identity = kind + '_' + uuid.uuid4().hex[:6]
        chosen = self.selected()
        inputs = compositor.NODES[kind]['inputs']
        after = chosen if (not connect and point is None and chosen in self.graph['nodes'] and self.graph['nodes'][chosen]['type'] != 'output' and inputs) else None
        if after is not None:
            # Added with a node selected: the new node goes after it in the chain, taking its picture and giving its
            # own to whatever took that picture before.
            place = self.graph['nodes'][after]['position']
            fed = self.consumers(after)
            self.graph['nodes'][identity] = {'type': kind, 'parameters': dict(settings), 'inputs': {inputs[0]: after},
                                             'position': [place[0] + WIDTH + 60, place[1]]}
            for other, key in fed:
                self.graph['nodes'][other]['inputs'][key] = identity
            self.make_room(identity)
        else:
            if point is None:
                point = self.view.mapToScene(self.view.viewport().rect().center())
            x, y = round(point.x() / GRID) * GRID, round(point.y() / GRID) * GRID
            if connect:
                # Dropped from an input: the new node stands to its left and feeds it.
                x -= WIDTH + 60
            self.graph['nodes'][identity] = {'type': kind, 'parameters': dict(settings), 'inputs': {}, 'position': self.free_place(x, y)}
            if connect and self.can_connect(identity, connect[0], connect[1]):
                self.graph['nodes'][connect[0]].setdefault('inputs', {})[connect[1]] = identity
        self.rebuild(); self.remember(before)
        self.canvas.clearSelection()
        if identity in self.items:
            self.items[identity].setSelected(True)

    def duplicate(self):
        chosen = [identity for identity in self.selected_nodes() if identity != self.graph['root']]
        if not chosen:
            return
        before = copy.deepcopy(self.graph); made = []
        for identity in chosen:
            copy_ = copy.deepcopy(self.graph['nodes'][identity]); new = copy_['type'] + '_' + uuid.uuid4().hex[:6]
            copy_['position'] = [copy_['position'][0] + 40, copy_['position'][1] + 40]
            self.graph['nodes'][new] = copy_; made.append(new)
        self.rebuild(); self.remember(before); self.canvas.clearSelection()
        for identity in made:
            self.items[identity].setSelected(True)

    def remove(self):
        chosen = [identity for identity in self.selected_nodes() if identity != self.graph['root']]
        if not chosen:
            if self.selected() == self.graph['root']:
                self.info.setText('The Composite node is where the graph ends, and stays.')
            return
        before = copy.deepcopy(self.graph)
        for identity in chosen:
            # What took this node's picture takes, in its place, the picture the node itself worked on: a node taken
            # out of a chain leaves the chain joined up.
            node = self.graph['nodes'][identity]
            ports = compositor.NODES[node['type']]['inputs']
            behind = (node.get('inputs') or {}).get(ports[0]) if ports else None
            for other, key in self.consumers(identity):
                if behind is not None and behind not in chosen:
                    self.graph['nodes'][other]['inputs'][key] = behind
            self.graph['nodes'].pop(identity, None)
        for node in self.graph['nodes'].values():
            node['inputs'] = {key: source for key, source in (node.get('inputs') or {}).items() if source in self.graph['nodes']}
        self.rebuild(); self.remember(before)

    def clear(self):
        before = copy.deepcopy(self.graph)
        self.graph = compositor.new(); self.rebuild(); self.remember(before); self.frame(everything=True)

    def show_composite(self):
        if self.write_timer.isActive():
            self.write_timer.stop(); self.write()
        # The list follows the scene's settings every half second; the buffer is chosen once it is there.
        def choose(tries=6):
            index = self.panel.buffer.findData('composite')
            if index >= 0:
                self.panel.buffer.setCurrentIndex(index); self.panel._buffer_picked = 'composite'
            elif tries:
                QtCore.QTimer.singleShot(300, lambda: choose(tries - 1))
            else:
                self.info.setText('There is no Composite buffer: the graph does nothing yet, or MoonLightIPR is chosen.')
        choose()

    def keyPressEvent(self, event):
        # Enter and Escape in a field must not close the window.
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter, QtCore.Qt.Key_Escape):
            event.accept(); return
        super().keyPressEvent(event)

    # ---- the selected node's settings ----
    def inspect(self, *args):
        while self.form.rowCount():
            self.form.removeRow(0)
        self.fields = []
        identity = self.selected()
        if identity is None or identity not in self.graph['nodes']:
            self.property_title.setText('Properties'); self.property_help.setText('Select a node to edit its settings.'); return
        node = self.graph['nodes'][identity]; schema = compositor.NODES[node['type']]
        self.property_title.setText(schema['label']); self.property_help.setText(schema['tip'])
        held = compositor.parameters(node)
        for key, spec in schema['parameters'].items():
            if spec[0] == 'number':
                field = QtWidgets.QDoubleSpinBox(); field.setDecimals(3); field.setRange(spec[2], spec[3])
                field.setSingleStep(max((spec[3] - spec[2]) / 200.0, 0.01)); field.setValue(float(held[key])); field.setKeyboardTracking(False)
                field.valueChanged.connect(lambda value, key=key: self.set_value(identity, key, float(value)))
            elif spec[0] == 'choice':
                field = QtWidgets.QComboBox(); field.addItems(list(spec[2])); field.setCurrentText(held[key])
                field.currentTextChanged.connect(lambda value, key=key: self.set_value(identity, key, value, redraw=True))
                if node['type'] == 'cryptomatte' and key == 'category':
                    # Another kind of matte: the names and IDs offered are that kind's.
                    field.currentTextChanged.connect(lambda value: QtCore.QTimer.singleShot(0, self.inspect))
            elif spec[0] == 'matte':
                field = QtWidgets.QComboBox()
                field.setToolTip('The names and IDs given in the Cryptomatte tabs of the scene\'s %ss.' % held['category'])
                offered = self.matte_choices(held['category'])
                for words, value in offered:
                    field.addItem(words, value)
                if held[key] and field.findData(held[key]) < 0:
                    field.addItem(held[key] + '  (no longer given)', held[key])
                if not offered and not held[key]:
                    field.addItem('(none given: name some in their Cryptomatte tabs)', '')
                field.setCurrentIndex(max(0, field.findData(held[key])))
                if not held[key] and field.itemData(0):
                    self.set_value(identity, key, field.itemData(0), redraw=True)
                field.currentIndexChanged.connect(lambda index, key=key, field=field: self.set_value(identity, key, field.itemData(index) or '', redraw=True))
            elif spec[0] == 'text':
                field = QtWidgets.QPlainTextEdit(held[key]); field.setMinimumHeight(140)
                field.textChanged.connect(lambda key=key, field=field: self.set_value(identity, key, field.toPlainText(), redraw=True))
            elif spec[0] == 'buffer':
                field = QtWidgets.QComboBox()
                for words, name in self.buffer_choices():
                    field.addItem(words, name)
                if field.findData(held[key]) < 0:
                    field.addItem(held[key], held[key])
                field.setCurrentIndex(field.findData(held[key]))
                field.currentIndexChanged.connect(lambda index, key=key, field=field: self.set_value(identity, key, field.itemData(index), redraw=True))
            else:
                field = QtWidgets.QWidget(); row = QtWidgets.QHBoxLayout(field); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(2)
                spins = []
                for part in held[key]:
                    spin = QtWidgets.QDoubleSpinBox(); spin.setDecimals(3); spin.setRange(0.0, 100.0); spin.setSingleStep(0.05); spin.setValue(float(part)); spin.setKeyboardTracking(False)
                    row.addWidget(spin); spins.append(spin)
                for spin in spins:
                    spin.valueChanged.connect(lambda value, key=key, spins=spins: self.set_value(identity, key, [s.value() for s in spins]))
            self.form.addRow(key, field); self.fields.append(field)
        if not schema['parameters']:
            self.property_help.setText(schema['tip'] + ' It has no settings.')

    def set_value(self, identity, key, value, redraw=False):
        node = self.graph['nodes'].get(identity)
        if node is None or self.busy:
            return
        before = copy.deepcopy(self.graph)
        node.setdefault('parameters', {})[key] = value
        if redraw:
            # What the node is called on the canvas follows this setting. The form is left as it is: the field that
            # was just changed must not be thrown away under the hand that changed it.
            item = self.items.get(identity)
            if item is not None:
                self.busy = True
                selected = item.isSelected(); self.canvas.blockSignals(True)
                self.canvas.removeItem(item); item = Node(self, identity, node); self.items[identity] = item; self.canvas.addItem(item)
                item.setSelected(selected); self.canvas.blockSignals(False); self.busy = False
                self.edges()
        self.remember(before)
