# python
"""Isolated GUI test: does Assign MoonShine Material tag every polygon of a mesh?"""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/assign-tags.json'
result = {}


def tags(mesh):
    return [polygon.materialTag for polygon in mesh.geometry.polygons]


try:
    from moonray_modo import properties
    for label, segments in (('cube', 1), ('dense', 4)):
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.cube on')
        for name, value in (('cenX', 0), ('cenY', 0.5), ('cenZ', 0), ('sizeX', 1.0), ('sizeY', 1.0), ('sizeZ', 1.0),
                            ('segmentsX', segments), ('segmentsY', segments), ('segmentsZ', segments)):
            lx.eval('tool.attr prim.cube %s %s' % (name, value))
        lx.eval('tool.apply')
        lx.eval('tool.set prim.cube off')
        mesh = modo.Scene().selectedByType('mesh')[0]
        before = tags(mesh)
        lx.eval('moonray.library.assign %s' % properties.encode({'shader': 'DwaBaseMaterial', 'parameters': {}}))
        after = tags(mesh)
        result[label] = {'polygons': len(after), 'before': sorted(set(before)), 'left_untagged': [i for i, tag in enumerate(after) if not tag.startswith('MoonShine_')]}
except Exception:
    result['error'] = traceback.format_exc()
out.write_text(json.dumps(result, indent=2, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('app.quit'))
