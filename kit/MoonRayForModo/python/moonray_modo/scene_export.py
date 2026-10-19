"""Export as MoonRay Scene (the MoonRay menu, and the preview window's Options): the Modo scene written as MoonRay reads it, to render with moonray.exe or on a
farm, without the preview window.

Its window asks for the file, the format and what to put in:
- RDLA: one text file, which MoonRay reads and a person can read too.
- RDLB: one binary file: smaller (about a third), quicker to load, the same picture.
- RDLA + RDLB: MoonRay's split scene, its settings as text and its geometry binary; MoonRay is given both.
- Render outputs: the scene's AOVs, Cryptomatte and deep output beside the beauty, or the beauty alone.
- Collect textures: every picture the scene reads copied into a folder beside it, named from the scene, the scene
  pointing to them there (paths relative to the scene's folder: render from that folder).
- Every frame of the frame range: one scene for each frame, numbered, as Render Animation would render them.
RDLB is MoonRay's own binary format, written by MoonRay's own converter (rdl2_convert) from the scene text the
plugin makes; that text goes through a temporary folder, not beside the scene."""
import hashlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PySide2 import QtCore, QtWidgets

FORMATS = (('rdla', 'RDLA: one text file'), ('rdlb', 'RDLB: one binary file (smaller, quicker to load)'),
           ('split', 'RDLA + RDLB: settings as text, geometry binary (MoonRay\'s split scene)'))
# What a scene names that is a file to collect.
COLLECTED = {'.tx', '.exr', '.hdr', '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.tga', '.bmp', '.vdb', '.pfm', '.cube', '.ies'}
STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')


class ExportDialog(QtWidgets.QDialog):
    def __init__(self, default_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Export as MoonRay Scene')
        self.settings = QtCore.QSettings('MoonRayForModo', 'SceneExport')
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)
        row = QtWidgets.QHBoxLayout()
        self.path = QtWidgets.QLineEdit(str(default_path))
        browse = QtWidgets.QPushButton('Browse...')
        browse.clicked.connect(self.browse)
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        form.addRow('File', row)
        self.format = QtWidgets.QComboBox()
        for key, label in FORMATS:
            self.format.addItem(label, key)
        self.format.setCurrentIndex(max(0, self.format.findData(self.settings.value('format', 'rdla'))))
        form.addRow('Format', self.format)
        self.outputs = QtWidgets.QCheckBox('Render outputs: AOVs, Cryptomatte and deep beside the beauty')
        self.outputs.setChecked(str(self.settings.value('outputs', 'true')).lower() == 'true')
        self.collect = QtWidgets.QCheckBox('Collect textures into a folder beside the scene')
        self.collect.setChecked(str(self.settings.value('collect', 'false')).lower() == 'true')
        self.collect.setToolTip('Every picture the scene reads is copied beside it, and the scene points there: render from the scene\'s folder.')
        self.frames = QtWidgets.QCheckBox('Every frame of the frame range, one scene each')
        self.frames.setChecked(str(self.settings.value('frames', 'false')).lower() == 'true')
        for box in (self.outputs, self.collect, self.frames):
            layout.addWidget(box)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText('Export')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setMinimumWidth(520)

    def browse(self):
        chosen, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Export as MoonRay Scene', self.path.text(), 'MoonRay scene (*.rdla *.rdlb)')
        if chosen:
            self.path.setText(chosen)

    def choices(self):
        held = {'path': Path(self.path.text()), 'format': self.format.currentData(), 'outputs': self.outputs.isChecked(),
                'collect': self.collect.isChecked(), 'frames': self.frames.isChecked()}
        for key in ('format', 'outputs', 'collect', 'frames'):
            self.settings.setValue(key, held[key] if key == 'format' else ('true' if held[key] else 'false'))
        return held


def converter(runtime):
    """MoonRay's scene converter, beside the runtime's libraries."""
    found = Path(runtime) / 'rdl2_convert.exe'
    if not found.is_file():
        raise ValueError('RDLB needs MoonRay\'s converter, rdl2_convert.exe, in the runtime: reinstall the kit, or export RDLA.')
    return found


def unescaped(text):
    return re.sub(r'\\(.)', lambda match: match.group(1), text)


def collect_textures(text, scene_path):
    """Copy every file the scene text names into <scene>_textures beside it, and point the text there by a path
    relative to the scene's folder. Returns the text and how many files were copied."""
    folder = scene_path.with_name(scene_path.stem + '_textures')
    copied = {}

    def placed(source):
        if source not in copied:
            folder.mkdir(exist_ok=True)
            # Pictures of the same name from different folders are kept apart by a short mark of where they were.
            mark = hashlib.sha1(str(source.parent).encode('utf-8')).hexdigest()[:6]
            target = folder / ('%s_%s' % (mark, source.name))
            if not target.exists():
                shutil.copyfile(str(source), str(target))
            copied[source] = target
        return copied[source]

    def replace(match):
        value = unescaped(match.group(1))
        if Path(value.replace('<UDIM>', '1001')).suffix.lower() not in COLLECTED:
            return match.group(0)
        if '<UDIM>' in value:
            pattern = Path(value)
            tiles = sorted(pattern.parent.glob(pattern.name.replace('<UDIM>', '[0-9][0-9][0-9][0-9]'))) if pattern.parent.is_dir() else []
            if not tiles:
                return match.group(0)
            for tile in tiles:
                placed(tile)
            first = copied[tiles[0]]
            name = first.name[:7] + pattern.name
            return '"%s/%s"' % (folder.name, name)
        source = Path(value)
        if not source.is_file():
            return match.group(0)
        return '"%s/%s"' % (folder.name, placed(source).name)
    return STRING.sub(replace, text), len(copied)


# A line of MoonRay's converter holding one string: an attribute (["name"] = "value",) or a metadata entry
# ({"name", "type", "value"},), the value written as it is, from its first quote to its last.
RAW_STRING = re.compile(r'^(\s*(?:\["[^"\\]*"\] = |\{"[^"\\]*", "[^"\\]*", ))"(.*)"(\}?,?)$')


def escaped(path):
    """MoonRay's converter writes the strings of a split scene's RDLA as they are, unescaped: a Windows path's
    backslashes and the quotes inside Cryptomatte's manifest then break MoonRay's reading of it. They are escaped
    again, as the plugin's own RDLA has them."""
    lines = path.read_text(encoding='utf-8').split('\n')
    for index, line in enumerate(lines):
        match = RAW_STRING.match(line)
        if match and ('"' in match.group(2) or '\\' in match.group(2)):
            lines[index] = '%s"%s"%s' % (match.group(1), match.group(2).replace('\\', '\\\\').replace('"', '\\"'), match.group(3))
    path.write_text('\n'.join(lines), encoding='utf-8')


def write(text, target, kind, runtime):
    """The scene text written as the format asked for; returns the files written."""
    target = Path(target)
    if kind == 'rdla':
        written = target.with_suffix('.rdla')
        written.write_text(text, encoding='utf-8')
        return [written]
    # The converter reads the scene text from a file: one in a temporary folder of its own, so nothing but the
    # scene asked for appears beside it.
    folder = Path(tempfile.mkdtemp(prefix='moonray-export-'))
    source = folder / (target.stem + '.rdla')
    source.write_text(text, encoding='utf-8')
    try:
        from . import native
        output = target.with_suffix('.rdlb') if kind == 'rdlb' else target.with_suffix('')
        done = subprocess.run([str(converter(runtime)), '-d', str(runtime), '-i', str(source), '-o', str(output)],
                              env=native.environment(Path(runtime)), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if done.returncode:
            raise ValueError('MoonRay could not convert the scene: ' + done.stdout.decode(errors='replace')[-600:])
        if kind == 'rdlb':
            return [output]
        escaped(output.with_suffix(".rdla"))
        return [output.with_suffix('.rdla'), output.with_suffix('.rdlb')]
    finally:
        shutil.rmtree(str(folder), ignore_errors=True)


def export(choices, warnings):
    """Write the scene (or each frame of the range) as chosen; returns the files written."""
    import lx
    import modo
    from . import host, native, rdla
    from .scene_setup import configure, values as scene_values
    from .preferences import Preferences
    runtime = native.find_runtime(Preferences().get('runtime') or native.default_runtime())
    held = scene_values()
    scene = modo.Scene()
    path = Path(choices['path'])
    if path.suffix.lower() not in ('.rdla', '.rdlb', ''):
        path = path.with_suffix('.rdla')
    selection = lx.service.Selection()
    now = selection.GetTime()
    fps = float(scene.fps)
    if choices['frames']:
        render = scene.renderItem
        first, last = int(round(float(render.channel('first').get()))), int(round(float(render.channel('last').get())))
        frames = [(frame, path.with_name('%s.%04d%s' % (path.stem, frame, path.suffix or '.rdla'))) for frame in range(first, last + 1)]
    else:
        frames = [(None, path)]
    written = []
    try:
        for frame, target in frames:
            if frame is not None:
                selection.SetTime(frame / fps)
            if held.get('final_motion'):
                from .animation import capture_current
                snapshot = capture_current(held['surface'] == 2)
            else:
                snapshot = host.snapshot(evaluated_geometry=held['surface'] == 2)
            configure(snapshot, held)
            if not choices['outputs']:
                snapshot['custom_aovs'] = []
                snapshot.pop('deep', None)
            text = rdla.scene_text(snapshot, snapshot['width'], snapshot['height'], held['samples'], held['environment'],
                                   str(target.with_suffix('.exr')))
            if choices['collect']:
                text, count = collect_textures(text, target)
            written += write(text, target, choices['format'], runtime)
            warnings.extend(w for w in snapshot.get('warnings', []) if w not in warnings)
    finally:
        selection.SetTime(now)
    return written


def run(parent=None):
    """Export as MoonRay Scene: the window, then the export."""
    import modo
    scene = modo.Scene()
    folder = Path(scene.filename).parent if getattr(scene, 'filename', None) else Path.home()
    name = Path(scene.filename).stem if getattr(scene, 'filename', None) else 'scene'
    held = QtCore.QSettings('MoonRayForModo', 'SceneExport').value('folder', '')
    default = Path(held) / (name + '.rdla') if held else folder / (name + '.rdla')
    dialog = ExportDialog(default, parent)
    if dialog.exec_() != QtWidgets.QDialog.Accepted:
        return None
    choices = dialog.choices()
    QtCore.QSettings('MoonRayForModo', 'SceneExport').setValue('folder', str(Path(choices['path']).parent))
    warnings = []
    written = export(choices, warnings)
    message = 'Exported %d file%s:\n%s' % (len(written), '' if len(written) == 1 else 's', '\n'.join(str(p) for p in written[:6]))
    if len(written) > 6:
        message += '\n...'
    if warnings:
        message += '\n\nNotices:\n' + '\n'.join(warnings[:8])
    QtWidgets.QMessageBox.information(parent, 'Export as MoonRay Scene', message)
    return written
