"""Small pictures of what each texture node makes, drawn on the node in the graph editor.

A colour correction, a ramp or a noise said nothing of what it did until the scene was rendered. Each texture node
that can be baked (graph_bake: one that depends on the UVs or a space, not on the camera or the surface's normal) is
rendered by MoonRay on its own, over one unit of UV, as MoonLightIPR's bakes are, at a size for the node, and shown on
it. The scene for it is written here, where Modo may be asked about textures. MoonRay is kept loaded for the editor
(persistent.Session), each picture a small change to the scene it has: a MoonRay started for each picture took five
seconds, almost all of it starting. Where the runtime cannot keep MoonRay loaded, or the session fails, MoonRay runs
once for each picture on a thread of its own, two at a time, as before. A picture is kept by the nodes that feed it,
so it is made once per change.
"""
import math
import struct
import subprocess
from pathlib import Path

from PySide2 import QtCore, QtGui
from shiboken2 import isValid

from . import graph_bake, nodes

SIZE = 96


class Signals(QtCore.QObject):
    ready = QtCore.Signal(str, str)


class Job(QtCore.QRunnable):
    """Render a node's bake and make a picture of it for the screen."""
    def __init__(self, key, render, exr, png, runtime, signals):
        super().__init__()
        self.key, self.render, self.exr, self.png, self.runtime, self.signals = key, render, exr, png, runtime, signals

    def run(self):
        try:
            if self.render is not None:
                self.render()
            from . import native
            staged = self.png.with_name(self.png.stem + '.tmp.png')
            subprocess.run([str(Path(self.runtime) / 'oiiotool.exe'), '--no-autopremult', str(self.exr), '--ch', 'R,G,B',
                            '--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o', str(staged)],
                           env=native.environment(self.runtime), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=60, check=True)
            staged.replace(self.png)
            self.signals.ready.emit(self.key, str(self.png))
        except Exception:
            self.signals.ready.emit(self.key, '')


def picture(width, height, pixels, png):
    """A rendered buffer (rows of three linear floats, the bottom row first) saved as an sRGB PNG at png."""
    values = struct.unpack('<%df' % (width * height * 3), pixels)

    def encoded(v):
        v = min(1.0, max(0.0, v if math.isfinite(v) else 0.0))
        return int(round(255 * (12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055)))
    rows = b''.join(bytes(encoded(v) for v in values[(height - 1 - y) * width * 3:(height - y) * width * 3]) for y in range(height))
    image = QtGui.QImage(rows, width, height, width * 3, QtGui.QImage.Format_RGB888)
    staged = Path(png).with_name(Path(png).stem + '.tmp.png')
    if not image.save(str(staged), 'PNG'):
        raise OSError('Cannot save ' + staged.name)
    staged.replace(png)


class Kept(QtCore.QObject):
    """A MoonRay kept loaded for the editor's pictures, given them one at a time: each, once rendered, saved as its PNG
    from the last picture MoonRay shows of it. failed(given): it could not go on; the pictures not made are given back."""
    def __init__(self, runtime, signals, failed, parent=None):
        super().__init__(parent)
        from .persistent import Session
        self.runtime, self.signals, self.failed = Path(runtime), signals, failed
        self.session = Session(self)
        self.session.memory_image.connect(self._image)
        self.session.ready.connect(self._done)
        self.session.failed.connect(self._failed)
        self.queue, self.now, self.last, self.generation = [], None, None, 0

    def add(self, key, text, png):
        self.queue.append((key, text, png))
        if self.now is None:
            self._next()

    def _next(self):
        if not self.queue:
            self.now = None
            return
        self.now = self.queue.pop(0)
        self.generation += 1
        self.last = None
        self.session.submit(self.now[1], self.runtime, 0, 'vectorized', self.generation)

    def _image(self, packet):
        if self.now is not None and packet[0] == self.generation and packet[1] == 'beauty':
            self.last = packet

    def _done(self, generation):
        if self.now is None or generation != self.generation:
            return
        key, _, png = self.now
        try:
            if self.last is None:
                raise ValueError('no picture')
            picture(self.last[2], self.last[3], self.last[4], png)
            self.signals.ready.emit(key, str(png))
        except Exception:
            self.signals.ready.emit(key, '')
        self._next()

    def _failed(self, message):
        given = ([self.now] if self.now else []) + self.queue
        self.queue, self.now = [], None
        self.failed(given)

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass


# A plain image node needs no render: its picture is its file, made small. The node's type and where it keeps the file.
IMAGE_NODES = {'image': 'file', 'ImageMap': 'texture'}
# What Qt reads itself, at the size wanted and in this process; the rest goes through the runtime's oiiotool.
QT_READS = {'.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff'}


# A UDIM set with no tile found: the colour MoonRay renders a missing image with, and the words drawn on it.
MISSING_COLOUR = '#ff00ff'
NO_TILES = 'No UDIM tiles found'


def udim_badge(tiles):
    """The words drawn over a UDIM set's picture: that it is a set, and of how many tiles."""
    return 'UDIM SET · %d' % len(tiles)


def image_file(graph, identity):
    """The file of a node that is an image and nothing more, as written (a UDIM set with <UDIM> in it); else None."""
    node = graph['nodes'].get(identity) or {}
    key = IMAGE_NODES.get(node.get('type'))
    if key is None:
        return None
    return str((node.get('parameters') or {}).get(key) or '') or None


def missing_set(graph, identity):
    """Whether a node's image is a UDIM set none of whose tiles are found: shown in the missing colour, said so."""
    from .graph_images import udim_tiles
    return udim_tiles(image_file(graph, identity)) == []


def image_source(graph, identity):
    """(file, linear, invert, badge) for a node that is an image and nothing more, its file on this machine; else None.
    linear: the file holds linear values (a float image, or a .tx not marked sRGB), brought to the screen's sRGB.
    A UDIM set is shown as its first tile that is there (the lowest number found, as the kit finds them at render
    time), with badge, the words drawn over it saying it is a set; a single image has none. Its 1001 was taken before,
    and a set without one, or not there, was drawn in MoonRay's missing-image magenta though it rendered."""
    node = graph['nodes'].get(identity) or {}
    key = IMAGE_NODES.get(node.get('type'))
    if key is None:
        return None
    parameters = node.get('parameters', {})
    name = str(parameters.get(key) or '')
    badge = None
    if '<UDIM>' in name:
        from .textures import source_tiles
        try:
            tiles = source_tiles(name)
        except (OSError, ValueError):
            tiles = {}
        if not tiles:
            return None
        first = min(tiles)
        name, badge = str(tiles[first]), udim_badge(sorted(tiles))
    if not name or not Path(name).is_file():
        return None
    suffix = Path(name).suffix.lower()
    srgb = bool(parameters.get('srgb', True)) and str(parameters.get('color_space', '')).lower() not in ('linear', 'raw', 'data')
    linear = suffix in ('.exr', '.hdr', '.pfm') or (suffix == '.tx' and not srgb)
    return Path(name), linear, bool(parameters.get('invert', False)), badge


def thumbnail_path(source, linear, invert, badge=None):
    """Where the picture of an image file is kept: named by the file as it stands, so a changed file is drawn again."""
    import hashlib
    held = source.stat()
    named = (str(source.resolve()), held.st_mtime_ns, held.st_size, linear, invert, SIZE)
    if badge:
        # A set's tile carries its words: another picture than the tile alone.
        named += (badge,)
    digest = hashlib.sha256(repr(named).encode()).hexdigest()[:24]
    folder = graph_bake.folder() / 'Thumbnails'
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (digest + '.png')


def draw_badge(image, words):
    """Words over the foot of a picture, light on a dark translucent band, legible over light or dark textures."""
    painter = QtGui.QPainter(image)
    try:
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
        font = QtGui.QFont()
        font.setPixelSize(max(9, image.height() // 9))
        font.setBold(True)
        painter.setFont(font)
        band = QtGui.QFontMetrics(font).height() + 4
        painter.fillRect(QtCore.QRect(0, image.height() - band, image.width(), band), QtGui.QColor(0, 0, 0, 170))
        painter.setPen(QtGui.QColor(255, 255, 255))
        painter.drawText(QtCore.QRect(4, image.height() - band, image.width() - 8, band), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, words)
    finally:
        painter.end()
    return image


class Thumbnail(QtCore.QRunnable):
    """An image node's picture: its file made small, by Qt where it reads the file and else by oiiotool; a UDIM set's
    with its badge drawn over it."""
    def __init__(self, key, source, linear, invert, png, runtime, signals, badge=None):
        super().__init__()
        self.key, self.source, self.linear, self.invert, self.png = key, source, linear, invert, png
        self.runtime, self.signals, self.badge = runtime, signals, badge

    def run(self):
        try:
            staged = self.png.with_name(self.png.stem + '.tmp.png')
            if self.source.suffix.lower() in QT_READS and not self.linear:
                reader = QtGui.QImageReader(str(self.source))
                size = reader.size()
                if size.isValid():
                    reader.setScaledSize(size.scaled(SIZE, SIZE, QtCore.Qt.KeepAspectRatio))
                image = reader.read()
                if image.isNull():
                    raise ValueError(reader.errorString())
                image = image.convertToFormat(QtGui.QImage.Format_RGB888)
                if self.invert:
                    image.invertPixels()
                if not image.save(str(staged), 'PNG'):
                    raise ValueError('Cannot write the picture')
            else:
                from . import native
                tail = (['--colorconvert', 'linear', 'sRGB'] if self.linear else []) + (['--invert'] if self.invert else []) + [
                    '-d', 'uint8', '-o', str(staged)]
                base = [str(Path(self.runtime) / 'oiiotool.exe'), '--no-autopremult', str(self.source)]
                fit = ['--fit', '%dx%d' % (SIZE, SIZE)]
                for channels in (['--ch', 'R,G,B'], []):     # a grey image has no G and B
                    done = subprocess.run(base + channels + fit + tail, env=native.environment(self.runtime), stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=60)
                    if done.returncode == 0:
                        break
                else:
                    raise ValueError(done.stdout.decode(errors='replace')[-300:])
            if self.badge:
                image = QtGui.QImage(str(staged)).convertToFormat(QtGui.QImage.Format_RGB888)
                if image.isNull() or not draw_badge(image, self.badge).save(str(staged), 'PNG'):
                    raise ValueError('Cannot mark the picture as a UDIM set')
            staged.replace(self.png)
            self.signals.ready.emit(self.key, str(self.png))
        except Exception:
            self.signals.ready.emit(self.key, '')


class Previews(QtCore.QObject):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.signals = Signals()
        self.signals.ready.connect(self.arrived)
        self.pool = QtCore.QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.pending, self.waiting = set(), {}
        # The MoonRay kept loaded for the pictures (Kept), made when first wanted; False once it cannot be used.
        self.kept = None
        # An edit is followed by a picture once the edits have paused.
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.refresh)

    def enabled(self):
        held = getattr(self.editor, 'show_previews', None)
        return held is None or held.isChecked()

    def wanted(self, identity):
        """Whether a node of the graph as it stands has a picture: a texture node that can be baked."""
        if not self.enabled():
            return False
        try:
            graph = nodes.effective(self.editor.graph)
            node = graph['nodes'].get(identity)
            # Image nodes only, shown as their file (IMAGE_NODES): nodes worked out by MoonRay are not rendered for a
            # picture of their own for now (0.5); the material widget's render shows what they make.
            return node is not None and node['type'] in IMAGE_NODES and nodes.category(node['type']) == 'map'
        except Exception:
            return False

    def schedule(self):
        if self.enabled():
            self.timer.start()

    def refresh(self):
        if not isValid(self.editor) or not self.enabled():
            return
        from . import native, persistent
        try:
            # The runtime chosen in Preview Preferences, else the kit's own (native.tool). It was asked of
            # find_runtime(None), which cannot be, and no picture was ever made.
            runtime = native.tool('moonray.exe').parent
        except Exception:
            return
        if self.kept is None:
            self.kept = Kept(runtime, self.signals, self._kept_failed, self) if persistent.supported(runtime) else False
        graph = nodes.effective(self.editor.graph)
        for identity, item in list(self.editor.items.items()):
            if not getattr(item, 'previewed', False):
                continue
            # An image node is shown as its file, made small: no MoonRay, a fraction of a second.
            try:
                image = image_source(graph, identity)
            except Exception:
                image = None
            if image is None and missing_set(graph, identity):
                # A UDIM set none of whose tiles are found: the missing colour, and why, not a render of nothing.
                item.show_preview(None, missing=NO_TILES)
                continue
            if image is not None:
                png = thumbnail_path(*image)
                if png.is_file():
                    item.show_preview(str(png))
                    continue
                key = str(png)
                self.waiting.setdefault(key, set()).add(identity)
                if key not in self.pending:
                    self.pending.add(key)
                    self.pool.start(Thumbnail(key, image[0], image[1], image[2], png, runtime, self.signals, badge=image[3]))
                continue
            try:
                exr, text = graph_bake.written(graph, identity, size=SIZE)
            except Exception:
                item.show_preview(None)
                continue
            png = exr.with_name(exr.stem + '.preview.png')
            if png.is_file():
                item.show_preview(str(png))
                continue
            key = str(png)
            self.waiting.setdefault(key, set()).add(identity)
            if key in self.pending:
                continue
            self.pending.add(key)
            if self.kept and text is not None:
                self.kept.add(key, text, png)
            else:
                self._alone(key, graph, identity, runtime, exr, png)

    def _alone(self, key, graph, identity, runtime, exr, png):
        """A picture made by a MoonRay of its own, on a thread of the pool."""
        try:
            exr, render = graph_bake.prepared(graph, identity, runtime, size=SIZE)
        except Exception:
            self.signals.ready.emit(key, '')
            return
        self.pool.start(Job(key, render, exr, png, runtime, self.signals))

    def _kept_failed(self, given):
        """The kept MoonRay could not go on: no more is asked of it, and what it had not made is made the old way."""
        kept, self.kept = self.kept, False
        if kept:
            QtCore.QTimer.singleShot(0, kept.close)
        for key, _, _ in given:
            self.pending.discard(key)
        self.schedule()

    def close(self):
        """The kept MoonRay let go (the editor closing)."""
        if self.kept:
            self.kept.close()
        self.kept = False

    @QtCore.Slot(str, str)
    def arrived(self, key, png):
        self.pending.discard(key)
        identities = self.waiting.pop(key, set())
        if not isValid(self.editor):
            return
        for identity in identities:
            item = self.editor.items.get(identity)
            if item is not None and isValid(item):
                item.show_preview(png or None)
