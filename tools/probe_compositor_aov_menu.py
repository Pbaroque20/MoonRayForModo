# python
"""Isolated GUI test: the compositor canvas's right-click Add Input AOV menu.

The compositor's editor is opened on a new scene. The Add Input AOV menu is filled and saved as a picture, with what it
offers noted. Then, as its entries would: the beauty is added wired into the Composite node's input, and a light pass
the scene has no output for is added, which puts that output in the scene."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/compositor-aov-menu'
out.mkdir(parents=True, exist_ok=True)
result = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def run():
    try:
        from moonray_modo import compositor_editor
        panel = panel_widget()
        panel.open_compositor()
        editor = compositor_editor._open.get('editor')
        menu = QtWidgets.QMenu(editor)
        sub = QtWidgets.QMenu('Add Input AOV', menu)
        menu.addMenu(sub)
        editor.aov_menu(sub)

        def listed(m):
            found = []
            for action in m.actions():
                if action.menu():
                    found.append({action.text(): listed(action.menu()), 'enabled': action.isEnabled()})
                elif action.text():
                    found.append(action.text())
            return found
        result['offered'] = listed(sub)
        sub.popup(editor.mapToGlobal(QtCore.QPoint(200, 120)))
        QtWidgets.QApplication.processEvents()
        sub.grab().save(str(out / 'menu.png'))
        first_pass = next(a for a in sub.actions() if a.menu() and a.text() == 'Light Pass').menu().actions()[0].data()
        sub.close()
        # The beauty, wired into the Composite node's input, as a right-click on that input would.
        root_node = editor.graph['root']
        before = set(editor.graph['nodes'])
        editor.add_aov(('buffer', 'beauty'), QtCore.QPointF(-300, 0), (root_node, 'image'))
        added = [n for n in editor.graph['nodes'] if n not in before]
        result['beauty_added'] = [editor.graph['nodes'][n]['parameters'] for n in added]
        result['composite_takes'] = editor.graph['nodes'][editor.graph['nodes'][root_node]['inputs']['image']]['parameters']
        # A light pass the render has no output for yet.
        before = set(editor.graph['nodes'])
        editor.add_aov(first_pass, QtCore.QPointF(-300, 200))
        added = [n for n in editor.graph['nodes'] if n not in before]
        result['pass_added'] = [editor.graph['nodes'][n]['parameters'] for n in added]
        result['outputs'] = [entry['name'] for entry in panel._settings_values().get('custom_aovs', [])]
        editor.frame(everything=True)
        QtWidgets.QApplication.processEvents()
        editor.grab().save(str(out / 'editor.png'))
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
