# python
"""Isolated GUI test: the compositor's Add Node popup, and the Build chooser's size.

The compositor's editor is opened. Build's chooser is shown with MoonRay's light passes, none ticked, and pictured. Tab
is pressed on the canvas: the Add Node popup should open with its field taking the keys. Then names are typed into it,
whole and in part, and the node each picks is noted; the popup is pictured; Enter adds the node picked."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/add-node'
out.mkdir(parents=True, exist_ok=True)
result = {'typed': {}}


def key(widget, which):
    """A key pressed and let go on a widget, as the keyboard sends it."""
    for kind in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
        QtWidgets.QApplication.sendEvent(widget, QtGui.QKeyEvent(kind, which, QtCore.Qt.NoModifier))


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def run():
    try:
        from moonray_modo import compositor, compositor_editor
        panel = panel_widget()
        panel.open_compositor()
        editor = compositor_editor._open.get('editor')
        QtWidgets.QApplication.processEvents()
        # Build's chooser, none ticked.
        chooser = compositor_editor.PassChooser(editor, 'Build from Light Passes', 'Choose the passes to work on, each with a Grade of '
                                                'its own. A pass not chosen stays in the Remainder.', list(compositor.PASSES), set())
        chooser.show()
        QtWidgets.QApplication.processEvents()
        result['chooser'] = {'size': [chooser.width(), chooser.height()], 'build_enabled': chooser.buttons.button(QtWidgets.QDialogButtonBox.Ok).isEnabled()}
        chooser.grab().save(str(out / 'chooser.png'))
        chooser.boxes[2].setChecked(True)
        result['chooser']['after_one_ticked'] = {'chosen': chooser.chosen(), 'build_enabled': chooser.buttons.button(QtWidgets.QDialogButtonBox.Ok).isEnabled()}
        chooser.close()
        # Tab on the canvas.
        view = editor.view
        view.setFocus()
        QtWidgets.QApplication.processEvents()
        before = set(editor.graph['nodes'])
        key(view, QtCore.Qt.Key_Tab)
        QtWidgets.QApplication.processEvents()
        popup = getattr(editor, 'popup', None)
        result['tab_opens_popup'] = bool(popup is not None and popup.isVisible())
        if popup is not None:
            result['field_has_focus'] = popup.search.hasFocus()
            result['listed'] = popup.results.count()
            for typed in ('gr', 'blur', 'mer', 'tone', 'zzz', 'sum'):
                popup.search.setText(typed)
                QtWidgets.QApplication.processEvents()
                item = popup.results.currentItem() if popup.results.currentRow() >= 0 else None
                result['typed'][typed] = item.text() if item is not None else None
            popup.search.setText('vign')
            QtWidgets.QApplication.processEvents()
            popup.grab().save(str(out / 'popup.png'))
            key(popup.search, QtCore.Qt.Key_Return)
            QtWidgets.QApplication.processEvents()
            added = [editor.graph['nodes'][n]['type'] for n in editor.graph['nodes'] if n not in before]
            result['enter_added'] = added
        editor.close()
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')


try:
    lx.eval('moonray.open')
except Exception:
    result['open_error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, run)
