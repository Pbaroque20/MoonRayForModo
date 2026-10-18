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
                'report', 'package', 'package_sequence', 'preview', 'playblast', 'cameras')


class Tools:
    def run(self, page):
        """Do what a menu entry or a form button names."""
        actions = {'preferences': self.edit_preferences, 'final': self.render_final, 'bake': self.bake_texture, 'export': self.export_moonray_scene,
                   'animation': self.render_animation, 'playblast': self.render_playblast, 'stop': self.stop, 'log': self.show_log,
                   'objects': self._edit_production, 'outputs': self._edit_outputs, 'colors': self._edit_assets,
                   'report': self._report_assets, 'package': self._package_assets,
                   'package_sequence': self._package_sequence, 'preview': lambda: None, 'cameras': self.camera_sequence}
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
            self._sync_output_menu(dialog.entries, self._display_filter_buffers())
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
        from . import image_formats
        filters, types = image_formats.picture_filters()
        dialog = QtWidgets.QFileDialog(self, 'Render to a file', str(self.settings.value('output/exr', '')))
        dialog.setAcceptMode(QtWidgets.QFileDialog.AcceptSave)
        dialog.setNameFilter(filters)
        held = str(self.settings.value('output/final_filter', ''))
        if held in types:
            dialog.selectNameFilter(held)
        if not dialog.exec_():
            return
        chosen_filter = dialog.selectedNameFilter()
        kind = types.get(chosen_filter, 'exr32')
        path = dialog.selectedFiles()[0]
        extension = image_formats.find(kind)[2]
        if Path(path).suffix.lower().lstrip('.') not in [e for e, k in image_formats.EXTENSIONS.items() if image_formats.find(k)[2] == extension]:
            path = str(Path(path).with_suffix('.' + extension)) if Path(path).suffix else path + '.' + extension
        self.settings.setValue('output/exr', str(Path(path).parent))
        self.settings.setValue('output/final_filter', chosen_filter)
        # MoonRay writes OpenEXR: in another type, the EXR is rendered beside the file asked for, and converted.
        asked = None if extension == 'exr' else {'type': kind, 'path': path, 'quality': int(self.settings.value('output/jpeg_quality', 92))}
        if asked:
            path = str(Path(path).with_suffix('.exr'))
        self.stop()
        self._stereo_after = {}
        try:
            scene = self._capture_output()
            if asked:
                scene['_export_as'] = asked
            from . import stereo
            if stereo.both(scene['camera']) and asked:
                # Each eye is converted beside its own EXR, named for the eye.
                scene['_export_as'] = dict(asked, path=None)
            if stereo.both(scene['camera']):
                # Both eyes: the left, then the right, each a render of its own beside the file chosen, named for the
                # eye; then, where the camera asks for one, their composite in the file chosen. Each step follows the
                # one before it finishing (panel._finished).
                left, right = str(stereo.eye_path(path, 'left')), str(stereo.eye_path(path, 'right'))
                kind = scene['camera']['stereo'].get('composite')
                self._stereo_after = {left: ('render', dict(scene, _stereo_eye='right'), right)}
                if kind in stereo.COMPOSITES:
                    self._stereo_after[right] = ('composite', kind, (left, right), path)
                self._submit(dict(scene, _stereo_eye='left'), left)
            else:
                self._submit(scene, path)
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

    def export_moonray_scene(self):
        """Export as MoonRay Scene, as the MoonRay menu has it: its window, then the export. ('export', the page an
        older MoonRay menu names, comes here too.)"""
        try:
            from .scene_export import run
            written = run(self)
            if written:
                self.status.setText('Exported ' + str(written[0]) + (' and %d more' % (len(written) - 1) if len(written) > 1 else ''))
        except Exception as exc:
            self._failed(str(exc))

    def camera_sequence(self):
        """The Camera Sequence window: cameras keyed to ranges of frames, kept with the scene."""
        import modo
        from .camera_sequence_dialog import CameraSequence
        from .host import channel
        scene = modo.Scene()
        render = scene.renderItem
        fps = float(scene.fps)
        # The scene's frame range: the Render item's, in frames.
        frames = (int(round(float(channel(render, 'first', 0)))), int(round(float(channel(render, 'last', 120)))))
        current = int(round(lx.service.Selection().GetTime() * fps))
        dialog = CameraSequence(self, self._settings_values().get('camera_sequence'), scene, frames, current)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        sequence = dialog.sequence()
        if self._store(camera_sequence=sequence):
            count = len(sequence['keys'])
            self.status.setText('Camera Sequence: %d key%s%s.' % (count, '' if count == 1 else 's', '' if sequence['enabled'] else ', off'))

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
                                 step=dialog.step.value(), prefix=dialog.prefix.text(), missing=dialog.missing.isChecked(),
                                 export_as=dialog.export_as())
            self.settings.setValue('output/animation', directory)
            self.stop()
            self.sequence = candidate
            self.sequence.start()
        except Exception as exc:
            self._failed(str(exc))

    def render_playblast(self):
        """MoonLightIPR Playblast: the animation rendered on the graphics card into a folder of PNGs, and played."""
        if self._output_busy():
            self.status.setText('An output render is running. Press Stop before starting a playblast.')
            return
        from .playblast import Playblast, PlayblastDialog, Player
        try:
            import modo
            # Never wider than the picture itself; a camera with a size of its own may narrow it further.
            widest = int(modo.Scene().renderItem.channel('resX').get())
        except Exception:
            widest = 8192
        size = self.preferences.get('preview_size')
        dialog = PlayblastDialog(self.settings, size if size > 0 else 640, widest, self.buffer.currentData() == 'denoised_beauty', self)
        if not dialog.exec_():
            return
        directory = dialog.folder.text().strip()
        try:
            candidate = Playblast(self, directory, dialog.first.value(), dialog.last.value(), dialog.fps.value(),
                                  step=dialog.step.value(), prefix=dialog.prefix.text(), width=dialog.width.value(),
                                  samples=dialog.samples.value())
            self.settings.setValue('output/playblast', directory)
            self.settings.setValue('output/playblast_samples', dialog.samples.value())
            self.stop()
            # The picture itself is wanted, and MoonLightIPR has its beauty and its denoised beauty to show.
            if self.draft.isChecked():
                self.draft.setChecked(False)
            if self.buffer.currentData() not in ('beauty', 'denoised_beauty'):
                self.buffer.setCurrentIndex(self.buffer.findData('beauty'))
            if dialog.play.isChecked():
                def play(files, fps=dialog.fps.value()/dialog.step.value()):
                    self._playblast_player = Player(files, fps, self)
                    self._playblast_player.show()
                candidate.done.connect(play)
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

    def buffer_names(self, frame):
        """The outputs a finished preview holds, as (key, what it is called), in the buffer list's order."""
        from . import options
        held = frame.get('files', {})
        named = {'beauty': 'Beauty', 'denoised_beauty': 'Denoised Beauty', 'denoise_albedo': 'Denoiser albedo', 'denoise_normal': 'Denoiser normal', 'denoise_fine': 'Denoiser fur matte'}
        named.update({key: label for key, (label, _, _) in options.AOVS.items()})
        # A display filter by its item's name.
        try:
            named.update({key: label for label, key in self._display_filter_buffers()})
        except Exception:
            pass
        order = ['beauty', 'denoised_beauty'] + list(options.AOVS)
        keys = [key for key in order if key in held] + sorted(key for key in held if key not in order)
        return [(key, named.get(key, key)) for key in keys]

    def export_buffers(self):
        """Save chosen outputs of the last finished preview, each as an image file of its own."""
        from . import outputs
        frame = self.renderer.buffers.frame
        if self.preview_engine.currentData() == 'moonlightipr':
            self.status.setText('MoonLightIPR renders the one picture; choose MoonRay to export its outputs.')
            return
        if not frame or not frame.get('files'):
            self.status.setText('Let a MoonRay preview finish first; its outputs are what is exported.')
            return
        from .export_dialog import ExportAOVs, group_of
        snapshot = frame.get('snapshot') or {}
        customs = {entry.get('name'): entry.get('kind') for entry in snapshot.get('custom_aovs') or []}
        entries = []
        for key, label in self.buffer_names(frame):
            kind = outputs.display_kind(snapshot, key)
            entries.append((key, label, group_of(key, kind, customs.get(key)), kind))
        # The size the render was made at, and the camera it was seen through.
        width, height = snapshot.get('width') or self.preview.image.width(), snapshot.get('height') or self.preview.image.height()
        identity = (snapshot.get('camera') or {}).get('identity')
        camera = identity or 'the render camera'
        try:
            import modo
            camera = modo.Scene().item(identity).name if identity else camera
        except Exception:
            pass
        about = 'Output Resolution: %d x %d based on %s' % (width, height, camera)
        dialog = ExportAOVs(self, entries, self.settings, about)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        chosen, folder = dialog.chosen(), Path(dialog.folder.text().strip())
        saved, failed = self.write_buffers(frame, chosen, folder, dialog.prefix.text().strip(), dialog.type(), dialog.quality.value())
        self.status.setText('Exported %d AOV%s to %s' % (len(saved), '' if len(saved) == 1 else 's', folder) + ('; could not write %s' % ', '.join(failed) if failed else ''))
        if saved and dialog.open_after.isChecked():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(folder)))

    def write_buffers(self, frame, keys, folder, prefix, kind, quality=92):
        """Write a render's outputs into a folder in a picture type (image_formats): as shown in the preview for the types
        of a picture to look at, with their own values for the linear ones. Returns (the files written, the outputs
        that could not be)."""
        import subprocess
        from . import image_formats, native, outputs
        from .display import values as display_values
        values = self._settings_values()
        display = display_values(dict(values['display'], working_space=frame['snapshot'].get('asset_settings', {}).get('working_space', 'rec709')))
        extension = image_formats.find(kind)[2]
        saved, failed = [], []
        for key in keys:
            source = frame['files'].get(key)
            target = Path(folder) / ('%s%s.%s' % (prefix + '_' if prefix else '', key, extension))
            try:
                if source is None or not Path(source).is_file():
                    raise OSError('not held')
                args = image_formats.arguments(kind, outputs.display_kind(frame['snapshot'], key), source, target, display, quality)
                done = subprocess.run([str(Path(frame['runtime']) / 'oiiotool.exe')] + args, env=native.environment(frame['runtime']), capture_output=True,
                                      creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=300)
                if done.returncode or not target.is_file():
                    raise OSError((done.stdout + done.stderr).decode(errors='replace')[-200:])
                saved.append(str(target))
            except (OSError, ValueError, subprocess.SubprocessError):
                failed.append(key)
        return saved, failed

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
