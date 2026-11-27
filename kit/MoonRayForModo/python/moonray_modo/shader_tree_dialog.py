"""MoonRay > Shader Tree -> MoonShine...: the one menu entry for moving Shader Tree images into MoonShine graphs. It asks
whether to convert the scene that is open (Move Shader Tree Textures to MoonShine Graphs, shader_tree_scene) or to open
a scene and convert it (Open Scene as MoonShine, moonshine_open), shows a progress bar while it works, and the summary
after. Its windows are the kit's own, parented to nothing of Modo's (quit_release: Modo's own Qt objects are never
wrapped)."""
import time


class Cancelled(Exception):
    """Cancel was pressed: what was being done stops, and nothing of it is left."""


class Progress:
    """A progress bar that repaints between steps, with Cancel. Where there is no window to draw (Modo's command line)
    it draws nothing and is never cancelled."""

    def __init__(self, title):
        self.dialog = None
        self.cancellable = True
        # The part of the bar what is reported now fills (start, length): opening a scene takes its first share.
        self.base = (0.0, 1.0)
        try:
            from PySide2 import QtCore, QtWidgets
            if QtWidgets.QApplication.instance() is None:
                return
            self.dialog = QtWidgets.QProgressDialog(title, 'Cancel', 0, 1000, None)
            self.dialog.setWindowTitle('Shader Tree -> MoonShine')
            self.dialog.setWindowModality(QtCore.Qt.ApplicationModal)
            self.dialog.setMinimumDuration(0)
            self.dialog.setAutoClose(False)
            self.dialog.setAutoReset(False)
            self.dialog.setMinimumWidth(460)
            self.dialog.show()
            self._pump()
        except Exception:
            self.dialog = None
        self._last = 0.0

    def _pump(self):
        from PySide2 import QtWidgets
        QtWidgets.QApplication.processEvents()

    def step(self, text, done=None, total=None):
        """Show a stage (and how far it has come); Cancelled where Cancel was pressed and stopping is still clean."""
        if self.dialog is None:
            return
        self.dialog.setLabelText(text)
        if done is not None and total:
            share = self.base[0] + self.base[1] * min(1.0, max(0.0, float(done) / total))
            self.dialog.setValue(int(1000 * share))
        self._pump()
        if self.cancellable and self.dialog.wasCanceled():
            raise Cancelled()

    def stage(self, text, start, end):
        """A part of the bar, start to end of it (0..1), for a stage of its own steps."""
        return _Part(self, text, start, end)

    def hold(self):
        """From here on what is begun is finished: Cancel no longer stops it."""
        self.cancellable = False
        if self.dialog is not None:
            self.dialog.setCancelButton(None)
            self._pump()

    def close(self):
        if self.dialog is not None:
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None


class _Part:
    def __init__(self, progress, text, start, end):
        self.progress, self.text, self.start, self.end = progress, text, start, end

    def step(self, detail, done, total):
        share = self.start + (self.end - self.start) * (float(done) / total if total else 1.0)
        self.progress.step('%s %s' % (self.text, detail) if detail else self.text, share, 1.0)


# The progress bar of the conversion running now, for the command to report to (shader_tree_scene.run), or None.
CURRENT = None


def has_layers():
    """Whether the open scene has image layers in its Shader Tree, switched on, to convert."""
    import modo
    try:
        return any(layer.channel('enable').get() for layer in modo.Scene().items('imageMap'))
    except Exception:
        return False


def summary(lines, title='Shader Tree -> MoonShine'):
    """The summary in a window (as well as the Event Log), where there is a window to show it in."""
    try:
        from PySide2 import QtWidgets
        if QtWidgets.QApplication.instance() is None:
            return
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Information, title, lines[0] if lines else 'Done.', QtWidgets.QMessageBox.Ok, None)
        if len(lines) > 1:
            box.setInformativeText('\n'.join(lines[1:6]) + ('\n...' if len(lines) > 6 else ''))
            box.setDetailedText('\n'.join(lines))
        box.exec_()
        box.deleteLater()
    except Exception:
        pass


def choose():
    """'current', 'open' or None (Cancel), as asked in a window; 'current' where there is no window to ask in."""
    try:
        from PySide2 import QtWidgets
        if QtWidgets.QApplication.instance() is None:
            return 'current'
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Question, 'Shader Tree -> MoonShine',
                                    "Move the Shader Tree's image layers into MoonShine graphs, so that Modo no longer holds the images.",
                                    QtWidgets.QMessageBox.NoButton, None)
        current = box.addButton('Convert the Current Scene', QtWidgets.QMessageBox.AcceptRole)
        opening = box.addButton('Open a Scene and Convert...', QtWidgets.QMessageBox.AcceptRole)
        box.addButton(QtWidgets.QMessageBox.Cancel)
        if not has_layers():
            box.setInformativeText('The open scene has no image layers switched on: there is nothing in it to convert.')
        box.exec_()
        clicked = box.clickedButton()
        box.deleteLater()
        return 'current' if clicked is current else 'open' if clicked is opening else None
    except Exception:
        return None


def run(choice=None, path=None, show=True):
    """The menu entry: ask, then convert the open scene or open one and convert it. Returns the summary lines. choice
    and path answer the questions beforehand (for scripts); show=False leaves the summary to the Event Log."""
    import lx
    import modo
    global CURRENT
    choice = choice or choose()
    if choice is None:
        return []
    if choice == 'open' and not path:
        path = modo.dialogs.customFile('fileOpen', 'Open a Scene and Convert', ('lxo',), ('Modo Scene',), ('*.lxo',))
        if not path:
            return []
    if choice == 'current' and not has_layers():
        lines = ['Nothing to convert: the open scene has no image layers switched on in its Shader Tree.']
        for line in lines:
            lx.out('MoonRay: ' + line)
        if show:
            summary(lines)
        return lines
    CURRENT = Progress('Reading the scene...')
    lines = []
    try:
        if choice == 'open':
            from . import moonshine_open
            lines = moonshine_open.open_scene(path, CURRENT)
        else:
            from . import shader_tree_scene
            lx.eval('moonray.material.moveShaderTreeTextures')
            lines = list(shader_tree_scene.LAST_REPORT)
    finally:
        CURRENT.close()
        CURRENT = None
    if show:
        summary(lines)
    return lines
