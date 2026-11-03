# python
"""Isolated GUI test: how quickly a DwaBaseMaterial's two lists come up.

The graph editor's property table: the material node selected, the time the table takes to fill, and how many rows have
their fields (a folded group's rows are made without them); a folded group opened, and a search into another, each with
its fields. The Properties panel: every control's question (whether it is enabled, its value) answered for one refresh,
timed with the kit's summary and read kept for each version of the tag, and read anew as before.
Writes test-results/material-lists/report.json and pictures."""
import json
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/material-lists'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))


def fields(editor):
    table = editor.table
    rows = [r for r in range(table.rowCount()) if r not in editor.group_rows]
    return {'rows': len(rows), 'with_fields': sum(1 for r in rows if table.cellWidget(r, 1) is not None),
            'shown': sum(1 for r in rows if not table.isRowHidden(r)), 'lazy_groups': sorted(getattr(editor, 'lazy_groups', set()))}


try:
    from moonray_modo import properties
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('moonray.library.assign %s' % properties.encode({'shader': 'DwaBaseMaterial', 'parameters': {}}))
    held['item'] = modo.Scene().selected[0]
except Exception:
    result['error'] = traceback.format_exc()
save()


def step2():
    try:
        from moonray_modo import material_override, shader_library
        item = held['item']
        keys = sorted(shader_library.catalog()['DwaBaseMaterial']['attributes'])
        # One refresh of the Properties panel: each control asks whether it is enabled, then its value.
        def refresh(summary, read):
            began = time.perf_counter()
            for key in keys:
                summary(item)
                material_override.driver(item, key)
                read(item).get('native_parameters', {}).get(key)
            return round((time.perf_counter() - began) * 1000, 1)
        def before_summary(it):
            return (material_override.enabled(properties.read(it)), material_override.effective(properties.read(it)).get('native_shader', ''))
        result['properties_controls'] = len(keys)
        result['properties_refresh_ms_before'] = refresh(before_summary, properties.read)
        material_override.summary(item);properties.peek(item)
        result['properties_refresh_ms_now'] = refresh(material_override.summary, properties.peek)
        from moonray_modo.node_editor import open_editor
        editor = held['editor'] = open_editor(item)
        editor.property_search.clear()
        root_id = editor.graph['root']
        editor.canvas.clearSelection();QtWidgets.QApplication.processEvents()
        began = time.perf_counter()
        editor.items[root_id].setSelected(True)
        editor.inspect()
        result['table_fill_ms'] = round((time.perf_counter() - began) * 1000, 1)
        result['table_first'] = fields(editor)
        editor.grab().save(str(out / 'table.png'))
        # A folded group opened: the list filled again, that group's rows with their fields.
        folded = sorted(editor.folded_groups())
        result['folded_at_first'] = folded
        group = 'Clearcoat' if 'Clearcoat' in folded else folded[0]
        row = next(r for r, g in editor.group_rows.items() if g == group)
        began = time.perf_counter()
        editor.fold_group(row)
        result['open_group'] = group
        result['open_group_ms'] = round((time.perf_counter() - began) * 1000, 1)
        result['table_after_open'] = fields(editor)
        result['opened_group_has_fields'] = all(editor.table.cellWidget(r, 1) is not None or r in editor.hidden_rows
                                               for r, g in editor.row_groups.items() if g == group and r not in editor.group_rows)
        editor.fold_group(next(r for r, g in editor.group_rows.items() if g == group))
        # A search into a folded group.
        began = time.perf_counter()
        editor.property_search.setText('glitter')
        QtWidgets.QApplication.processEvents()
        result['search_ms'] = round((time.perf_counter() - began) * 1000, 1)
        result['table_after_search'] = fields(editor)
        editor.grab().save(str(out / 'table-search.png'))
        editor.property_search.clear()
    except Exception:
        result['step2_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(800, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(4000, step2)
