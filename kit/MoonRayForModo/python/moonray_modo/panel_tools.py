"""What the preview window does besides previewing: output renders, exports, packaging and the
dialogs for the scene data that has no place in a properties form. The MoonRay menu, the Render
item's form and the window's own menus all come here through Panel.run().
"""
from pathlib import Path
from PySide2 import QtCore, QtGui, QtWidgets
import lx
from . import properties, rdla


# What Panel.run() does in the window; any other page is a group of render settings.
WINDOW_PAGES = ('preferences', 'final', 'bake', 'export', 'animation', 'stop', 'log', 'objects', 'outputs', 'colors',
                'report', 'package', 'package_sequence', 'preview')


class Tools:
    def run(self, page):
        """Do what a menu entry or a form button names."""
        actions = {'preferences': self.edit_preferences, 'final': self.render_final, 'bake': self.bake_texture, 'export': self.export,
                   'animation': self.render_animation, 'stop': self.stop, 'log': self.show_log,
                   'objects': self._edit_production, 'outputs': self._edit_outputs, 'colors': self._edit_assets,
                   'report': self._report_assets, 'package': self._package_assets,
                   'package_sequence': self._package_sequence, 'preview': lambda: None}
        # Anything else names a group of render settings, which are on the Render item.
        actions.get(page, self.open_settings)()

    def open_settings(self):
        try:
            import modo
            lx.eval('select.item {%s} set' % modo.Scene().renderItem.id)
            self.status.setText('Render item selected: its MoonRay properties hold the render settings.')
        except Exception as exc:
            self.status.setText('Cannot select the Render item: ' + str(exc))

    def edit_preferences(self):
        from .preferences import Dialog
        if Dialog(self.preferences, self).exec_():
            self._preferences_changed()

    def _store(self, **changes):
        """Write settings to the scene, through the undoable command."""
        stored = properties.scene_settings()
        stored.update(changes)
        try:
            lx.eval('moonray.sceneSettings ' + properties.encode(stored))
            return True
        except Exception as exc:
            self.status.setText('Cannot store settings: ' + str(exc))
            return False

    def _edit_outputs(self):
        from .outputs_dialog import OutputsDialog
        dialog = OutputsDialog(self._settings_values()['custom_aovs'], self)
        if dialog.exec_() and self._store(custom_aovs=dialog.entries):
            self._sync_output_menu(dialog.entries)
            self.status.setText('Named outputs updated. Render to fill the new buffers.')

    def _edit_assets(self):
        from .assets_dialog import AssetsDialog
        dialog = AssetsDialog(self._settings_values()['asset_settings'], self)
        if dialog.exec_() == QtWidgets.QDialog.Accepted and self._store(asset_settings=dialog.entries):
            self.changes.invalidate()

    def _edit_production(self):
        from .production_dialog import Controls
        dialog = Controls(self._settings_values()['production'], self)
        if dialog.exec_() == QtWidgets.QDialog.Accepted and self._store(production=dialog.values):
            self.changes.invalidate()
            self.status.setText('Scene controls saved. Render to apply.')

    def _report_assets(self):
        try:
            from .assets import inventory
            scene = self._capture()
            entries = inventory(scene)
            text = '\n'.join(('%s | %d file(s) | %.1f MB | %s' % ('MISSING' if v['missing'] else 'Found', v['tiles'], v['bytes'] / 1048576, v['path'])) for v in entries)
            text += '\n\nScene notices:\n' + '\n'.join(scene.get('warnings', []))
            dialog = QtWidgets.QDialog(self)
            dialog.setWindowTitle('Scene asset report')
            dialog.resize(900, 480)
            layout = QtWidgets.QVBoxLayout(dialog)
            view = QtWidgets.QPlainTextEdit(text)
            view.setReadOnly(True)
            layout.addWidget(view)
            dialog.exec_()
        except Exception as exc:
            self._failed(str(exc))

    def _package_assets(self):
        path = self._save_path('New portable scene folder', 'package', '', 'All names (*)')
        if not path:
            return
        try:
            from .assets import package
            scene = self._capture_output()
            width, height = self._dimensions(scene, True)
            values = self._settings_values()
            output = package(scene, path, width, height, values['samples'], values['environment'])
            self.status.setText('Packaged render scene: ' + output)
        except Exception as exc:
            self._failed(str(exc))

    def _package_sequence(self):
        if getattr(getattr(self, 'packaging', None), 'running', False):
            return
        if self._output_busy():
            self.status.setText('Wait for the active output to finish before packaging.')
            return
        import modo
        first, ok = QtWidgets.QInputDialog.getInt(self, 'Package animation', 'First frame', 1, -100000, 100000)
        if not ok:
            return
        last, ok = QtWidgets.QInputDialog.getInt(self, 'Package animation', 'Last frame', first, first, 100000)
        if not ok:
            return
        step, ok = QtWidgets.QInputDialog.getInt(self, 'Package animation', 'Frame step', 1, 1, 10000)
        if not ok:
            return
        path = self._save_path('New sequence package folder', 'sequence', '', 'All names (*)')
        if not path:
            return
        try:
            from .package_sequence import PackageSequence
            self.packaging = PackageSequence(self, path, first, last, step, float(modo.Scene().fps), self._settings_values()['final_motion'])
            self.packaging.start()
        except Exception as exc:
            self._failed(str(exc))

    def _save_path(self, title, key, suffix, name_filter):
        dialog = QtWidgets.QFileDialog(self, title, str(self.settings.value('output/' + key, '')))
        dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptSave)
        dialog.setNameFilter(name_filter)
        dialog.setDefaultSuffix(suffix)
        if not dialog.exec_():
            return ''
        path = dialog.selectedFiles()[0]
        self.settings.setValue('output/' + key, str(Path(path).parent))
        return path

    def render_final(self):
        if self._output_busy():
            self.status.setText('An output render is running. Press Stop before starting another.')
            return
        path = self._save_path('Render OpenEXR', 'exr', 'exr', 'OpenEXR (*.exr)')
        if not path:
            return
        self.stop()
        try:
            self._submit(self._capture_output(), path)
        except Exception as exc:
            self._failed(str(exc))

    def bake_texture(self):
        """Render what MoonRay sees on the selected mesh into a picture laid out by its UVs."""
        import modo
        from . import bake
        if self._output_busy():
            self.status.setText('An output render is running. Press Stop before starting another.')
            return
        chosen = [item for item in modo.Scene().selected if item.type == 'mesh']
        if len(chosen) != 1:
            self.status.setText('Select the one mesh to bake, then choose Bake Selected Mesh to Texture again.')
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle('Bake %s to a texture' % chosen[0].name)
        form = QtWidgets.QFormLayout(dialog)
        note = QtWidgets.QLabel('MoonRay renders the lighting and materials on this mesh into a picture laid out by its UVs.\n'
                                'The outputs ticked in the render settings are baked with it.')
        note.setWordWrap(True)
        form.addRow(note)
        size = QtWidgets.QComboBox()
        for value in bake.SIZES:
            size.addItem('%d x %d' % (value, value), value)
        size.setCurrentIndex(max(0, size.findData(int(self.settings.value('bake/size', 2048)))))
        form.addRow('Size', size)
        udim = QtWidgets.QSpinBox()
        udim.setRange(1001, 1999)
        udim.setToolTip('Which tile of the UVs is baked. 1001 is the first: U and V from 0 to 1.')
        form.addRow('UDIM tile', udim)
        mode = QtWidgets.QComboBox()
        for label, value in bake.MODES:
            mode.addItem(label, value)
        mode.setCurrentIndex(mode.findData(3))
        mode.setToolTip('Where each point of the surface is looked at from. Down the normal bakes what does not depend on the view;\n'
                        'from the camera keeps the highlights and reflections the render camera would see.')
        form.addRow('Looked at', mode)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        path = self._save_path('Bake to OpenEXR', 'bake', 'exr', 'OpenEXR (*.exr)')
        if not path:
            return
        self.settings.setValue('bake/size', size.currentData())
        self.stop()
        try:
            self._submit(bake.scene(self._capture_output(), chosen[0].id, size.currentData(), udim.value(), mode.currentData()), path)
        except Exception as exc:
            self._failed(str(exc))

    def export(self):
        path = self._save_path('Export MoonRay scene', 'rdla', 'rdla', 'MoonRay scene (*.rdla)')
        if not path:
            return
        try:
            scene = self._capture_output()
            width, height = self._dimensions(scene, True)
            values = self._settings_values()
            text = rdla.scene_text(scene, width, height, values['samples'], values['environment'],
                                   str(Path(path).with_suffix('.exr')))
            Path(path).write_text(text, encoding='utf-8')
            self.status.setText('Exported ' + path)
        except Exception as exc:
            self._failed(str(exc))

    def render_animation(self):
        if self._output_busy():
            self.status.setText('An output render is running. Press Stop before starting an animation.')
            return
        from .output_dialog import AnimationDialog
        from .animation import Sequence
        dialog = AnimationDialog(self.settings, self)
        if not dialog.exec_():
            return
        directory = dialog.folder.text().strip()
        try:
            candidate = Sequence(self, directory, dialog.first.value(), dialog.last.value(),
                                 dialog.fps.value(), dialog.motion.isChecked(),
                                 step=dialog.step.value(), prefix=dialog.prefix.text(), missing=dialog.missing.isChecked())
            self.settings.setValue('output/animation', directory)
            self.stop()
            self.sequence = candidate
            self.sequence.start()
        except Exception as exc:
            self._failed(str(exc))

    def copy_image(self):
        if self.preview.image.isNull():
            self.status.setText('Render a preview first.')
            return
        QtWidgets.QApplication.clipboard().setImage(self.preview.image)
        self.status.setText('Displayed image copied. Use Render EXR for linear output.')

    def save_preview(self):
        if self.preview.image.isNull():
            self.status.setText('Render a preview first.')
            return
        path = self._save_path('Save preview', 'png', 'png', 'PNG image (*.png)')
        if path:
            self.status.setText('Saved ' + path if self.preview.image.save(path, 'PNG') else 'Could not save the preview image.')

    def show_log(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle('MoonRay render log')
        dialog.resize(820, 500)
        layout = QtWidgets.QVBoxLayout(dialog)
        row = QtWidgets.QHBoxLayout()
        layout.addLayout(row)
        search = QtWidgets.QLineEdit()
        search.setPlaceholderText('Find in render log')
        row.addWidget(search, 1)
        find = QtWidgets.QPushButton('Find next')
        row.addWidget(find)
        text = QtWidgets.QPlainTextEdit(self.renderer.log or 'No renderer output yet.')
        text.setReadOnly(True)
        layout.addWidget(text)

        def find_next():
            if not search.text():
                return
            follow.setChecked(False)
            if not text.find(search.text()):
                cursor = text.textCursor()
                cursor.movePosition(QtGui.QTextCursor.Start)
                text.setTextCursor(cursor)
                text.find(search.text())
        find.clicked.connect(find_next)
        search.returnPressed.connect(find_next)
        footer = QtWidgets.QHBoxLayout()
        layout.addLayout(footer)
        copy = QtWidgets.QPushButton('Copy log')
        copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(text.toPlainText()))
        footer.addWidget(copy)
        save = QtWidgets.QPushButton('Save log...')
        footer.addWidget(save)

        def save_log():
            path = self._save_path('Save render log', 'log', 'txt', 'Text (*.txt)')
            if path:
                try:
                    Path(path).write_text(text.toPlainText(), encoding='utf-8')
                except OSError as exc:
                    QtWidgets.QMessageBox.warning(dialog, 'Cannot save log', str(exc))
        save.clicked.connect(save_log)
        follow = QtWidgets.QCheckBox('Follow live output')
        follow.setChecked(True)
        footer.addWidget(follow)
        footer.addStretch()
        timer = QtCore.QTimer(dialog)
        timer.setInterval(750)

        def refresh():
            current = self.renderer.log or 'No renderer output yet.'
            if follow.isChecked() and current != text.toPlainText():
                text.setPlainText(current)
                bar = text.verticalScrollBar()
                bar.setValue(bar.maximum())
        timer.timeout.connect(refresh)
        timer.start()
        dialog.exec_()
        timer.stop()
