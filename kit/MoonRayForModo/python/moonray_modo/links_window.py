"""MoonRay > Links: the Links panel's window (links.py), as Adobe Illustrator's Links panel lists placed images: each
mesh of the scene with its state (Linked, Editing, Embedded), its status and its file, and what can be done with it.
The list is looked at again every few seconds while the window is open, and after each save."""
import json
from pathlib import Path

from PySide2 import QtCore, QtGui, QtWidgets

from . import links

COLUMNS = ('Name', 'State', 'Status', 'Stand-in', 'File')
# A status's colour: up to date in yellow (his choice), what needs looking at in orange, a missing file in red.
COLOURS = {links.OK: '#e8d44d', links.EDITED: '#f0902e', links.CHANGED: '#f0902e', links.BOTH: '#e8601c',
           links.MISSING: '#e05050'}
TIPS = {
    'link': 'Write each selected embedded mesh to an .lxo file of its own and put a Scene Proxy in its place: the '
            'scene keeps a light stand-in, the mesh is read from its file.',
    'edit': 'Bring each selected linked mesh back into the scene from its file, to edit it. It stays tied to its file: '
            'saving the scene writes your edits to it.',
    'update': 'Write each selected mesh you are editing to its file now; it stays editable. A selected linked mesh '
              'whose file changed on disk is read again from it.',
    'done': 'Write each selected mesh you are editing to its file and make it a linked proxy again.',
    'relink': 'Point the selected linked mesh at another .lxo file.',
    'reveal': 'Show the selected row\'s file in Explorer.',
    'select': 'Select the selected rows\' items in Modo.',
    'embed': 'Make each selected linked mesh a mesh of the scene again, no longer tied to its file (the file stays '
             'on disk). A mesh you are editing is untied from its file.',
    'standin': 'Choose what each selected linked mesh is drawn as in the viewport: a low-res everyday object from the '
               "Asset Library's stand-ins, stretched to the mesh's size, or the mesh itself. Renders always use the mesh.",
}


class Window(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, QtCore.Qt.Window)
        self.setWindowTitle('Links')
        self.resize(900, 480)
        self.settings = QtCore.QSettings('MoonRayForModo', 'Links')
        layout = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel('Meshes linked to .lxo files of their own are Scene Proxies, light in the scene. Edit one in '
                                'the scene to change it: saving the scene writes it back to its file, and Done Editing makes it '
                                'a proxy again.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(list(COLUMNS))
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree.setSortingEnabled(False)
        # A long path cut in its middle: its folder's start and the file's name stay in sight.
        self.tree.setTextElideMode(QtCore.Qt.ElideMiddle)
        self.tree.header().setStretchLastSection(True)
        for column, width in enumerate((190, 80, 200, 110)):
            self.tree.setColumnWidth(column, width)
        self.tree.itemSelectionChanged.connect(self._enable)
        self.tree.itemDoubleClicked.connect(lambda *_: self._select_items())
        layout.addWidget(self.tree, 1)
        self.buttons = {}
        for keys in (('link', 'edit', 'update', 'done'), ('relink', 'standin', 'reveal', 'select', 'embed')):
            row = QtWidgets.QHBoxLayout()
            for key in keys:
                label = {'link': 'Link...', 'edit': 'Edit in Scene', 'update': 'Update File', 'done': 'Done Editing',
                         'relink': 'Relink...', 'standin': 'Stand-in...', 'reveal': 'Reveal in Explorer', 'select': 'Select Item',
                         'embed': 'Embed'}[key]
                button = QtWidgets.QPushButton(label)
                button.setToolTip(TIPS[key])
                button.clicked.connect(getattr(self, '_' + key))
                row.addWidget(button)
                self.buttons[key] = button
            row.addStretch(1)
            layout.addLayout(row)
        # Link draws each mesh as a stand-in from the Asset Library, chosen by its name (standins.choose), unless off.
        self.with_standins = QtWidgets.QCheckBox('Link with stand-ins from the Asset Library')
        self.with_standins.setToolTip('Each mesh linked is drawn in the viewport as a low-res everyday object from the '
                                      "Asset Library's stand-ins, chosen by its name (a box where none fits) and stretched to "
                                      'its size. Renders use the mesh itself.')
        self.with_standins.setChecked(str(self.settings.value('standins', 'true')).lower() == 'true')
        self.with_standins.toggled.connect(lambda on: self.settings.setValue('standins', 'true' if on else 'false'))
        layout.addWidget(self.with_standins)
        foot = QtWidgets.QHBoxLayout()
        self.embedded = QtWidgets.QCheckBox('Show embedded meshes')
        self.embedded.setChecked(str(self.settings.value('embedded', 'true')).lower() == 'true')
        self.embedded.toggled.connect(self._embedded_toggled)
        self.status = QtWidgets.QLabel()
        refresh = QtWidgets.QPushButton('Refresh')
        refresh.clicked.connect(self.refresh)
        foot.addWidget(self.embedded)
        foot.addWidget(self.status, 1)
        foot.addWidget(refresh)
        layout.addLayout(foot)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self._tick)
        self.rows = []
        links.LISTENERS.append(self._saved)
        self.refresh()

    # The list.
    def refresh(self):
        """The rows looked at again, the selection kept by item where the item is still there."""
        chosen = {item.data(0, QtCore.Qt.UserRole) for item in self.tree.selectedItems()}
        try:
            self.rows = links.rows(embedded=self.embedded.isChecked())
        except Exception as exc:
            self.status.setText('The scene could not be read: %s' % exc)
            return
        self.tree.blockSignals(True)
        self.tree.clear()
        for row in self.rows:
            item = QtWidgets.QTreeWidgetItem([row['name'], links.STATE_TEXT[row['state']], links.STATUS_TEXT[row['status']],
                                              (row.get('standin') or 'None') if row['state'] != links.EMBEDDED else '',
                                              row['file'] or ''])
            item.setData(0, QtCore.Qt.UserRole, row['id'])
            item.setToolTip(4, row['file'] or 'Embedded: a mesh of the scene, no file.')
            colour = COLOURS.get(row['status'])
            if colour:
                item.setForeground(2, QtGui.QBrush(QtGui.QColor(colour)))
            self.tree.addTopLevelItem(item)
            if row['id'] in chosen:
                item.setSelected(True)
        self.tree.blockSignals(False)
        self._enable()
        self._said()

    def _said(self):
        counts = {}
        for row in self.rows:
            counts[row['state']] = counts.get(row['state'], 0) + 1
        waiting = sum(1 for row in self.rows if row['status'] in links.NEEDS_WRITE)
        words = ['%d %s' % (counts[state], links.STATE_TEXT[state].lower()) for state in (links.LINKED, links.EDITING, links.EMBEDDED) if counts.get(state)]
        if waiting:
            words.append('%d to write at the next save' % waiting)
        self.status.setText(', '.join(words) or 'No meshes in the scene.')

    def _chosen(self, *states):
        ids = {item.data(0, QtCore.Qt.UserRole) for item in self.tree.selectedItems()}
        return [row for row in self.rows if row['id'] in ids and (not states or row['state'] in states)]

    def _enable(self):
        for key, states in (('link', (links.EMBEDDED,)), ('edit', (links.LINKED,)), ('update', (links.EDITING,)),
                            ('done', (links.EDITING,)), ('embed', (links.LINKED, links.EDITING))):
            self.buttons[key].setEnabled(bool(self._chosen(*states)))
        # Update File also reads a linked mesh's file again where it changed on disk (links.update, reload).
        self.buttons['update'].setEnabled(bool(self._updatable()))
        one = self._chosen()
        self.buttons['relink'].setEnabled(len(one) == 1 and one[0]['state'] in (links.LINKED, links.EDITING))
        self.buttons['reveal'].setEnabled(len(one) == 1 and bool(one[0]['file']))
        self.buttons['standin'].setEnabled(bool(self._chosen(links.LINKED, links.EDITING)))
        self.buttons['select'].setEnabled(bool(one))

    def _updatable(self):
        return [row for row in self._chosen() if row['state'] == links.EDITING or (row['state'] == links.LINKED and row['status'] == links.CHANGED)]

    def _tick(self):
        """Looked at again while shown and Modo is not in the middle of a drag."""
        try:
            from .interaction import dragging
            if dragging():
                return
        except Exception:
            pass
        if self.isVisible():
            self.refresh()

    def _saved(self, written):
        self.refresh()
        if written:
            self.status.setText('%d mesh%s written to %s file%s on save. ' % (len(written), '' if len(written) == 1 else 'es',
                                'its' if len(written) == 1 else 'their', '' if len(written) == 1 else 's') + self.status.text())

    def _embedded_toggled(self, on):
        self.settings.setValue('embedded', 'true' if on else 'false')
        self.refresh()

    # What is done: each action one command (links.run, moonray.links.act), one step to undo.
    def _act(self, what, action, ids, path=''):
        try:
            done = links.run(action, ids, path)
        except Exception as exc:
            self.refresh()
            self.status.setText('%s failed: %s' % (what, exc))
            return None
        self.refresh()
        return done

    def _link(self):
        rows = self._chosen(links.EMBEDDED)
        if not rows:
            return
        try:
            import modo
            scene_file = modo.Scene().filename
        except Exception:
            scene_file = None
        # Beside the scene, in '<scene>_links', unless another folder is chosen; a scene not saved yet starts where the
        # last one went.
        start = self.settings.value('folder', '') or ''
        default = links.default_folder(scene_file)
        made = False
        if default is not None:
            try:
                made = not default.exists()
                default.mkdir(parents=True, exist_ok=True)
                start = str(default)
            except OSError:
                pass
        chosen = QtWidgets.QFileDialog.getExistingDirectory(self, 'Folder the linked meshes are written to', start)
        if made and (not chosen or not links.same_file(chosen, default)):
            # The folder made for the dialog, let go of where another was chosen or none.
            try:
                default.rmdir()
            except OSError:
                pass
        if not chosen:
            return
        self.settings.setValue('folder', chosen)
        how = json.dumps({'folder': chosen, 'standin': 'auto' if self.with_standins.isChecked() else 'none'})
        made = self._act('Link', 'link', [row['id'] for row in rows], how)
        if made is not None:
            self.status.setText('%d linked. %s' % (len(made), self.status.text()))

    def _edit(self):
        self._act('Edit in Scene', 'edit', [row['id'] for row in self._chosen(links.LINKED)])

    def _update(self):
        done = self._act('Update File', 'update', [row['id'] for row in self._updatable()])
        if done is not None:
            self.status.setText('%d written. %s' % (len(done), self.status.text()))

    def _done(self):
        self._act('Done Editing', 'done', [row['id'] for row in self._chosen(links.EDITING)])

    def _relink(self):
        rows = self._chosen(links.LINKED, links.EDITING)
        if len(rows) != 1:
            return
        start = str(Path(rows[0]['file']).parent) if rows[0]['file'] else ''
        chosen, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'File %s is linked to' % rows[0]['name'], start, 'Modo scene (*.lxo)')
        if chosen:
            self._act('Relink', 'relink', [rows[0]['id']], chosen)

    def _standin(self):
        """A menu of the Asset Library's stand-ins: the one chosen is what each selected linked mesh is drawn as."""
        rows = self._chosen(links.LINKED, links.EDITING)
        if not rows:
            return
        from . import standins
        menu = QtWidgets.QMenu(self)
        menu.addAction('By its name (from the library)').setData(standins.AUTO)
        menu.addSeparator()
        for entry in standins.catalog():
            menu.addAction(entry['name']).setData(entry['name'])
        menu.addSeparator()
        menu.addAction('None: the mesh itself').setData(standins.NONE)
        chosen = menu.exec_(self.buttons['standin'].mapToGlobal(QtCore.QPoint(0, self.buttons['standin'].height())))
        if chosen is not None:
            self._act('Stand-in', 'standin', [row['id'] for row in rows], chosen.data())

    def _reveal(self):
        rows = self._chosen()
        if len(rows) == 1 and rows[0]['file']:
            links.reveal(rows[0]['file'])

    def _select(self):
        self._select_items()

    def _select_items(self):
        rows = self._chosen()
        if rows:
            try:
                links.select([row['id'] for row in rows])
            except Exception as exc:
                self.status.setText('Select failed: %s' % exc)

    def _embed(self):
        self._act('Embed', 'embed', [row['id'] for row in self._chosen(links.LINKED, links.EDITING)])

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.timer.stop()
        if self._saved in links.LISTENERS:
            links.LISTENERS.remove(self._saved)
        super().closeEvent(event)


_window = None
_quit_hooked = [False]


def _close_on_quit():
    """Modo quitting closes the window first, while Qt still stands (as the Rhizome and Convert LXO to RDL windows do).
    Reference cycles are collected on Modo's main thread from the first window on (main_thread_gc)."""
    from . import main_thread_gc
    main_thread_gc.install()
    if _quit_hooked[0]:
        return
    application = QtCore.QCoreApplication.instance()
    if application is None:
        return

    def closing():
        global _window
        from shiboken2 import isValid
        window, _window = _window, None
        try:
            if window is not None and isValid(window):
                window.close()
                window.deleteLater()
        except Exception:
            pass
    application.aboutToQuit.connect(closing)
    _quit_hooked[0] = True


def show(parent=None):
    global _window
    if _window is None:
        _window = Window(parent)
        _close_on_quit()
    elif _saved_listener_missing():
        links.LISTENERS.append(_window._saved)
    _window.refresh()
    _window.show()
    _window.raise_()
    _window.activateWindow()
    return _window


def _saved_listener_missing():
    return _window is not None and _window._saved not in links.LISTENERS
