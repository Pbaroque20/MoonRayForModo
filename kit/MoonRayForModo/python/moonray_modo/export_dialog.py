"""The Export AOVs window: the outputs of the last finished render, grouped by what they are, saved as picture files of
a chosen type into a chosen folder."""
from pathlib import Path
from PySide2 import QtCore, QtWidgets

from . import image_formats, options

GROUPS = ('Pictures', 'Light', 'Surface data', 'Mattes', 'Render statistics', 'Denoiser guides')
STATISTICS = ('sample_count', 'time_per_pixel')
LIGHT_RESULT = 8


def group_of(key, kind, custom):
    """Which group an output is listed under, by its key, how it is shown (outputs.display_kind) and its own kind."""
    if key.startswith('denoise_'):
        return 'Denoiser guides'
    if kind == 'cryptomatte' or custom == 'cryptomatte':
        return 'Mattes'
    if key in STATISTICS:
        return 'Render statistics'
    if key in options.AOVS:
        return 'Light' if options.AOVS[key][1].get('result') == LIGHT_RESULT else 'Surface data'
    if custom == 'lpe':
        return 'Light'
    if custom in ('material', 'depth', 'normal', 'position', 'motion', 'alpha'):
        return 'Surface data'
    return 'Pictures'


class ExportAOVs(QtWidgets.QDialog):
    """Choose outputs, a picture type, a folder and a name; the files that will be written are named as the choices
    change."""
    def __init__(self, parent, entries, settings, about=''):
        super().__init__(parent)
        self.setWindowTitle('Export AOVs')
        self.resize(560, 600)
        self.settings = settings
        layout = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QLabel(about or 'The outputs of the last finished render.')
        heading.setWordWrap(True)
        layout.addWidget(heading)
        # The outputs, under their groups, each a checkbox as Modo draws them; a group's own checkbox ticks all of it.
        self.items, self.groups = [], {}
        holder = QtWidgets.QWidget()
        rows = QtWidgets.QVBoxLayout(holder)
        rows.setContentsMargins(6, 6, 6, 6); rows.setSpacing(2)
        for group in GROUPS:
            members = [entry for entry in entries if entry[2] == group]
            if not members:
                continue
            whole = QtWidgets.QCheckBox(group)
            font = whole.font(); font.setBold(True); whole.setFont(font)
            whole.setTristate(False)
            rows.addWidget(whole)
            boxes = []
            for key, label, _, kind in members:
                box = QtWidgets.QCheckBox(label)
                box.setToolTip(key)
                box.setChecked(group in ('Pictures', 'Light'))
                box.key, box.kind = key, kind
                box.setContentsMargins(20, 0, 0, 0)
                line = QtWidgets.QHBoxLayout(); line.setContentsMargins(22, 0, 0, 0); line.addWidget(box); line.addStretch(1)
                rows.addLayout(line)
                box.toggled.connect(lambda on, g=group: self.follow(g))
                boxes.append(box)
                self.items.append(box)
            whole.clicked.connect(lambda on, members=boxes: [box.setChecked(on) for box in members if box.isEnabled()])
            self.groups[group] = (whole, boxes)
        rows.addStretch(1)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        layout.addWidget(scroll, 1)
        ticks = QtWidgets.QHBoxLayout()
        for text, state in (('Select All', True), ('Select None', False)):
            button = QtWidgets.QPushButton(text)
            button.setAutoDefault(False)
            button.clicked.connect(lambda checked=False, s=state: [box.setChecked(s) for box in self.items if box.isEnabled()])
            ticks.addWidget(button)
        ticks.addStretch(1)
        layout.addLayout(ticks)
        form = QtWidgets.QFormLayout()
        self.kind = QtWidgets.QComboBox()
        for key, label, extension, numbers, shown in image_formats.FORMATS:
            self.kind.addItem(label, key)
        stored = str(settings.value('output/aov_type', 'png8'))
        self.kind.setCurrentIndex(max(0, self.kind.findData(stored)))
        form.addRow('Type', self.kind)
        self.quality = QtWidgets.QSpinBox()
        self.quality.setRange(1, 100)
        self.quality.setValue(int(settings.value('output/jpeg_quality', 92)))
        self.quality.setSuffix(' %')
        form.addRow('JPEG quality', self.quality)
        self.colour = QtWidgets.QLabel()
        self.colour.setWordWrap(True)
        form.addRow('Colour', self.colour)
        row = QtWidgets.QHBoxLayout()
        self.folder = QtWidgets.QLineEdit(str(settings.value('output/aovs', '')))
        browse = QtWidgets.QPushButton('Browse...')
        browse.setAutoDefault(False)
        browse.clicked.connect(self.browse)
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        form.addRow('Folder', row)
        self.prefix = QtWidgets.QLineEdit(str(settings.value('output/aov_prefix', 'render')))
        self.prefix.setToolTip('What each file\'s name starts with: render gives render_beauty.png, render_albedo.png and so on.')
        form.addRow('Name', self.prefix)
        self.names = QtWidgets.QLabel()
        self.names.setWordWrap(True)
        self.names.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        form.addRow('Files', self.names)
        self.open_after = QtWidgets.QCheckBox('Open the folder when done')
        self.open_after.setChecked(str(settings.value('output/aov_open', 'false')).lower() == 'true')
        form.addRow('', self.open_after)
        layout.addLayout(form)
        self.buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setText('Export')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.kind.currentIndexChanged.connect(self.update)
        self.prefix.textChanged.connect(self.update)
        self.folder.textChanged.connect(self.update)
        for group in self.groups:
            self.follow(group)
        self.update()

    def follow(self, group):
        """A group's checkbox is ticked when all of it is, and the files are named again."""
        whole, boxes = self.groups[group]
        offered = [box for box in boxes if box.isEnabled()]
        whole.blockSignals(True)
        whole.setChecked(bool(offered) and all(box.isChecked() for box in offered))
        whole.blockSignals(False)
        if hasattr(self, 'names'):
            self.update()

    def browse(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, 'Folder for the exported AOVs', self.folder.text())
        if folder:
            self.folder.setText(folder)

    def type(self):
        return self.kind.currentData()

    def chosen(self):
        return [box.key for box in self.items if box.isChecked() and box.isEnabled()]

    def target(self, key):
        extension = image_formats.find(self.type())[2]
        prefix = self.prefix.text().strip()
        return Path(self.folder.text().strip()) / ('%s%s.%s' % (prefix + '_' if prefix else '', key, extension))

    def update(self, *args):
        """What the choices come to: the outputs a type cannot hold set aside, the colour said, the files named."""
        key = self.type()
        linear = image_formats.linear(key)
        exr = image_formats.find(key)[2] == 'exr'
        for box in self.items:
            refused = box.kind == 'cryptomatte' and not exr
            box.setEnabled(not refused)
            box.setToolTip('A Cryptomatte is saved as OpenEXR only: its IDs are numbers the other types cannot hold.' if refused else box.key)
        self.quality.setEnabled(image_formats.find(key)[2] == 'jpg')
        self.colour.setText('The render\'s own linear values, as they are.' if linear else
                            'As the preview shows it: through the view transform, with data outputs shown as greys and colours.')
        chosen = self.chosen()
        folder = self.folder.text().strip()
        if not chosen:
            self.names.setText('Tick the outputs to export.')
        else:
            shown = [self.target(name).name for name in chosen[:4]]
            more = len(chosen) - len(shown)
            self.names.setText(', '.join(shown) + (' and %d more' % more if more > 0 else ''))
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(bool(chosen and folder))

    def accept(self):
        folder = Path(self.folder.text().strip())
        if not folder.is_dir():
            QtWidgets.QMessageBox.warning(self, 'Export AOVs', 'That folder does not exist: choose one with Browse.')
            return
        existing = [self.target(key).name for key in self.chosen() if self.target(key).exists()]
        if existing:
            asked = QtWidgets.QMessageBox.question(self, 'Export AOVs', '%d file%s there already: %s%s. Replace %s?' % (
                len(existing), ' is' if len(existing) == 1 else 's are', ', '.join(existing[:3]), ' ...' if len(existing) > 3 else '',
                'it' if len(existing) == 1 else 'them'), QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel)
            if asked != QtWidgets.QMessageBox.Yes:
                return
        self.settings.setValue('output/aovs', str(folder))
        self.settings.setValue('output/aov_type', self.type())
        self.settings.setValue('output/aov_prefix', self.prefix.text())
        self.settings.setValue('output/jpeg_quality', self.quality.value())
        self.settings.setValue('output/aov_open', 'true' if self.open_after.isChecked() else 'false')
        super().accept()
