"""A window to look at a picture from the asset library: as large as the window, zoomed with the wheel and moved by
dragging, as the preview window's picture is; and the library's other pictures one after another.

Pictures Qt reads are shown as they are. An OpenEXR, a Radiance HDR or a MoonRay .tx holds linear values, and is shown
through the image tool from the kit's runtime, made sRGB as the preview shows a render."""
import subprocess
import tempfile
from pathlib import Path
from PySide2 import QtCore, QtGui, QtWidgets

# What the viewer shows: what Qt reads, and what the image tool makes a picture of first.
READ = ('.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp', '.tga')
LINEAR = ('.exr', '.hdr', '.tx')
VIEWABLE = READ + LINEAR


def viewable(path):
    return Path(str(path)).suffix.lower() in VIEWABLE


def read(path):
    """A picture of the file to show, and a line of what it holds; raises ValueError where it cannot be shown."""
    path = Path(path)
    image = QtGui.QImage(str(path)) if path.suffix.lower() in READ else QtGui.QImage()
    words = ''
    if image.isNull():
        from . import native
        from PySide2 import QtCore as _core
        # The runtime chosen in the preview's preferences, as the RDL importer takes it.
        runtime = Path(native.configured_runtime(_core.QSettings('MoonRayForModo', native.settings_name())))
        with tempfile.TemporaryDirectory(prefix='MoonRayViewer-') as folder:
            target = Path(folder) / 'shown.png'
            done = subprocess.run([str(runtime / 'oiiotool.exe'), '--no-autopremult', str(path), '--ch', 'R,G,B', '--colorconvert', 'linear', 'sRGB',
                                   '-d', 'uint8', '-o', str(target)], env=native.environment(runtime), stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, timeout=120, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if done.returncode or not target.is_file():
                raise ValueError('The picture could not be read: ' + done.stdout.decode('utf-8', errors='replace')[-200:])
            image = QtGui.QImage(str(target)).copy()
        words = 'linear values, shown in sRGB'
    if image.isNull():
        raise ValueError('The picture could not be read')
    size = path.stat().st_size
    held = '%.1f MB' % (size / 1048576.0) if size >= 1048576 else '%d KB' % max(1, size // 1024)
    return image, ', '.join(part for part in ('%d x %d' % (image.width(), image.height()), held, words) if part)


class ImageViewer(QtWidgets.QDialog):
    def __init__(self, paths, index=0, parent=None):
        super().__init__(parent)
        self.paths, self.index = list(paths), index
        self.resize(1000, 700)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        bar = QtWidgets.QHBoxLayout()
        self.previous = QtWidgets.QPushButton('< Previous')
        self.next = QtWidgets.QPushButton('Next >')
        fit = QtWidgets.QPushButton('Fit')
        actual = QtWidgets.QPushButton('Actual Size')
        reveal = QtWidgets.QPushButton('Show in Folder')
        for button in (self.previous, self.next, fit, actual, reveal):
            button.setAutoDefault(False)
            button.setFocusPolicy(QtCore.Qt.NoFocus)
        bar.addWidget(self.previous)
        bar.addWidget(self.next)
        bar.addStretch(1)
        self.where = QtWidgets.QLabel()
        bar.addWidget(self.where)
        bar.addStretch(1)
        bar.addWidget(fit)
        bar.addWidget(actual)
        bar.addWidget(reveal)
        layout.addLayout(bar)
        from .viewer import SoftwarePreview
        self.view = SoftwarePreview()
        layout.addWidget(self.view, 1)
        self.about = QtWidgets.QLabel()
        self.about.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(self.about)
        self.previous.clicked.connect(lambda: self.step(-1))
        self.next.clicked.connect(lambda: self.step(1))
        fit.clicked.connect(self.view.fit)
        actual.clicked.connect(self.view.actual_size)
        reveal.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(Path(self.paths[self.index]).parent))))
        self.show_current()

    def show_current(self):
        path = Path(self.paths[self.index])
        self.setWindowTitle(path.name)
        self.where.setText('%d of %d' % (self.index + 1, len(self.paths)) if len(self.paths) > 1 else '')
        self.previous.setEnabled(self.index > 0)
        self.next.setEnabled(self.index < len(self.paths) - 1)
        try:
            image, words = read(path)
            self.view.set_image(image)
            self.view.fit()
            self.about.setText('%s  |  %s' % (words, path))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            self.view.clear()
            self.about.setText('%s  |  %s' % (exc, path))

    def step(self, by):
        index = self.index + by
        if 0 <= index < len(self.paths):
            self.index = index
            self.show_current()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (QtCore.Qt.Key_Left, QtCore.Qt.Key_PageUp):
            self.step(-1)
        elif key in (QtCore.Qt.Key_Right, QtCore.Qt.Key_PageDown, QtCore.Qt.Key_Space):
            self.step(1)
        elif key == QtCore.Qt.Key_F:
            self.view.fit()
        elif key == QtCore.Qt.Key_1:
            self.view.actual_size()
        else:
            super().keyPressEvent(event)


def show(paths, index=0, parent=None):
    viewer = ImageViewer(paths, index, parent)
    viewer.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    viewer.show()
    return viewer
