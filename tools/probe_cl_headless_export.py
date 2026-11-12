# python
"""Command-line (modo_cl): a scene exported as MoonRay reads it with no window, as the README's headless steps say:
a lit cube, moonray_modo.scene_export.export() to RDLA and to RDLB, and for each the files written and the notices.
Writes test-results/headless-export/report.json and the scenes beside it."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\headless-export')
out.mkdir(parents=True, exist_ok=True)
report = {}
try:
    lx.eval('scene.new')
    scene = modo.Scene()
    mesh = scene.addMesh('Cube')
    with mesh.geometry as geo:
        c = [geo.vertices.new((a - .5, b - .5, d - .5)) for a in (0, 1) for b in (0, 1) for d in (0, 1)]
        for f in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            geo.polygons.new([c[i] for i in f])
    from moonray_modo import scene_export
    for kind in ('rdla', 'rdlb'):
        warnings = []
        written = scene_export.export({'path': str(out / ('cube.' + kind)), 'format': kind, 'frames': False, 'outputs': True,
                                       'collect': False}, warnings)
        report[kind] = {'written': [str(p) for p in written], 'warnings': warnings[:5]}
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
