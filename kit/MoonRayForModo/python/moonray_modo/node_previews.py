"""Small pictures of what each texture node makes, drawn on the node in the graph editor.

A colour correction, a ramp or a noise said nothing of what it did until the scene was rendered. Each texture node
that can be baked (graph_bake: one that depends on the UVs or a space, not on the camera or the surface's normal) is
rendered by MoonRay on its own, over one unit of UV, as MoonLightIPR's bakes are, at a size for the node, and shown on
it. The scene for it is written here, where Modo may be asked about textures; MoonRay runs on a thread of its own, two
at a time, so the editor does not wait. A picture is kept by the nodes that feed it, so it is made once per change.
"""
import subprocess
from pathlib import Path

from PySide2 import QtCore
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


class Previews(QtCore.QObject):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.signals = Signals()
        self.signals.ready.connect(self.arrived)
        self.pool = QtCore.QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.pending, self.waiting = set(), {}
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
            return node is not None and nodes.category(node['type']) == 'map' and graph_bake.reason(graph, identity) is None
        except Exception:
            return False

    def schedule(self):
        if self.enabled():
            self.timer.start()

    def refresh(self):
        if not isValid(self.editor) or not self.enabled():
            return
        from . import native
        try:
            runtime = native.find_runtime(None)
        except Exception:
            return
        graph = nodes.effective(self.editor.graph)
        for identity, item in list(self.editor.items.items()):
            if not getattr(item, 'previewed', False):
                continue
            try:
                exr, render = graph_bake.prepared(graph, identity, runtime, size=SIZE)
            except Exception:
                item.show_preview(None)
                continue
            png = exr.with_name(exr.stem + '.preview.png')
            if png.is_file():
                item.show_preview(str(png))
                continue
            key = str(png)
            self.waiting.setdefault(key, set()).add(identity)
            if key not in self.pending:
                self.pending.add(key)
                self.pool.start(Job(key, render, exr, png, runtime, self.signals))

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
