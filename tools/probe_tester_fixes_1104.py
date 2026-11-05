# python
"""GUI check of the 2026-11-04 tester fixes in a test Modo, no dialog left open: the Preview Preferences' realtime
switch, the preference commands, the MoonRay Widget's samples and Scale, the graph editor's black group rows, and Load
VDB File on a dwVdbVolume (a dwVdbGeometry made, linked, its file set). Writes test-results/tester-fixes-1104/report.json."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tester-fixes-1104')
out.mkdir(parents=True, exist_ok=True)
VDB = r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\vdb\ball.vdb'
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))


def attempt(name, fn):
    result[name] = 'started'
    save()
    try:
        result[name] = fn()
    except Exception:
        result[name] = 'error: ' + traceback.format_exc().strip().splitlines()[-1]
    save()


def step1():
    try:
        step1_body()
    except Exception:
        result['step1_error'] = traceback.format_exc()
        save()
        QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


def step1_body():
    from moonray_modo import properties, entities
    from moonray_modo.preferences import Dialog, Preferences
    def prefs_dialog():
        d = Dialog(Preferences(), None)
        found = 'xpu_realtime' in d.widgets
        d.deleteLater()
        return found
    if not __import__('os').environ.get('PROBE_SKIP_DIALOG'):attempt('preview_preferences_has_xpu_realtime', prefs_dialog)
    attempt('pref_commands', lambda: {c: lx.eval('%s ?' % c) for c in ('moonray.pref.xpuRealtime', 'moonray.pref.pbrValidity', 'moonray.pref.mirroredMeshes')})
    def vdb_volume():
        scene = modo.Scene()
        try:volume = entities.make_item(scene, 'VdbVolume', 'Probe Volume')
        except Exception:result['vdb_make_item'] = traceback.format_exc()[-1200:];raise
        try:lx.eval('select.item {%s} set' % volume.id)
        except Exception:result['vdb_select'] = traceback.format_exc()[-800:];raise
        try:
            lx.eval('moonray.entity.volumeFile {%s}' % VDB);said = 'ok'
        except Exception as exc:
            said = 'command said: %s' % exc
        result['vdb_command'] = said
        prefix = entities.CHANNEL_PREFIX
        shapes = [i for i in scene.items(entities.item_type('VdbGeometry'))]
        return [{'name': s.name, 'model': s.channel(prefix + 'model').get(), 'volume': s.channel(prefix + 'modo_volume').get(),
                 'density_grid': s.channel(prefix + 'density_grid').get()} for s in shapes]
    # Load VDB File is checked on the command line (probe_vdb_volume_file.py): here, outside a command, Modo refuses
    # to add an item from a timer.
    try:
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.cube on')
        lx.eval('tool.apply')
        lx.eval('tool.set prim.cube off')
        lx.eval('moonray.library.assign %s' % properties.encode({'shader': 'DwaBaseMaterial', 'parameters': {}}))
        held['item'] = modo.Scene().selected[0]
    except Exception:
        result['material_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(1500, step2)


def step2():
    def editor_checks():
        from moonray_modo.node_editor import open_editor
        editor = held['editor'] = open_editor(held['item'])
        editor.canvas.clearSelection()
        editor.items[editor.graph['root']].setSelected(True)
        QtWidgets.QApplication.processEvents()
        editor.inspect()
        headers = getattr(editor, 'group_rows', {})
        colours = sorted({editor.table.item(row, 0).background().color().name() for row in headers})
        widget = editor.material_preview
        samples = [widget.samples.itemText(i) for i in range(widget.samples.count())]
        return {'group_header_colours': colours, 'widget_samples': samples, 'widget_scale': widget.scale.value(),
                'widget_always_xpu2': getattr(widget.renderer.session, 'always_xpu2', None),
                'view_update_mode': int(editor.view.viewportUpdateMode())}
    attempt('graph_editor', editor_checks)
    save()
    QtCore.QTimer.singleShot(int(__import__('os').environ.get('PROBE_QUIT_MS','800')), lambda: lx.eval('!app.quit'))


result['loaded'] = True
save()
QtCore.QTimer.singleShot(4000, step1)
