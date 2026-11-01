# python
"""Command-line test: a MoonRay disk light under an unevenly scaled parent, and one the scale tool scaled unevenly, say they stay
round. A disk with an even scale says nothing. Writes test-results/cl-round-light/report.json."""
import json
import pathlib
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/cl-round-light'
out.mkdir(parents=True, exist_ok=True)
result = {}

try:
    from moonray_modo import entities, host
    scene = modo.Scene()
    kind = entities.item_type('DiskLight')
    even = scene.addItem(kind, name='Even')
    under = scene.addItem(kind, name='Under')
    parent = scene.addItem('locator', name='Parent')
    under.setParent(parent)
    modo.LocatorSuperType(parent).scale.set((2.0, 5.0, 1.0))
    tooled = scene.addItem(kind, name='Tooled')
    entities.SCALED_UNEVENLY[tooled.id] = True
    def notes():
        return [str(line) for line in host.snapshot().get('warnings', []) if 'stays round' in str(line)]
    result['first reading'] = notes()
    result['second reading'] = notes()
    result['done'] = True
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1))
