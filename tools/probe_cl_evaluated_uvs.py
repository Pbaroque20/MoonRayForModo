# python
"""Command line: Modo's evaluated surfaces (render cache) beside their meshes as read directly: vertex and face counts,
UV features Modo gave, and whether the evaluated points are the mesh's points (same order, or same places). PROBE_SCENE
the .lxo. Writes test-results/evaluated-uvs/report.json."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\evaluated-uvs')
out.mkdir(parents=True, exist_ok=True)
report = {}
try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    from moonray_modo import evaluated
    data = evaluated.capture(lx.service.Selection().GetTime())
    scene = modo.Scene()
    rows = []
    for surface in data['surfaces']:
        prototype = data['prototypes'][str(surface['source_id'])]
        row = {'item': surface['source_item'], 'material': surface.get('material'),
               'features': [(f['type'], f['name']) for f in prototype['features']],
               'segments': [{'vertices': len(s['vertices']), 'faces': len(s['faces']),
                             'per face': len(s['faces'][0]) if len(s['faces']) else 0,
                             'uv sets': len(s.get('uv_sets') or []), 'face varying': s.get('face_varying')}
                            for s in prototype['segments']]}
        try:
            item = scene.item(surface['source_item'])
            row['item name'] = item.name
            row['type'] = item.type
            if item.type == 'mesh':
                geo = item.geometry
                points = [tuple(v.position) for v in geo.vertices]
                row['points'] = len(points)
                row['polygons'] = len(geo.polygons)
                row['uv maps'] = [m.name for m in geo.vmaps.uvMaps]
                if prototype['segments']:
                    seg = prototype['segments'][0]
                    vs = [tuple(v) for v in seg['vertices']]
                    row['same order'] = len(vs) == len(points) and all(
                        max(abs(a - b) for a, b in zip(p, q)) < 1e-5 for p, q in zip(vs, points))
                    places = {tuple(round(c, 5) for c in p) for p in points}
                    row['same places'] = sum(tuple(round(c, 5) for c in v) in places for v in vs) / max(1, len(vs))
        except Exception:
            row['item error'] = traceback.format_exc()[-300:]
        rows.append(row)
    report['surfaces'] = rows
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
