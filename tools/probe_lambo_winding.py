# python
"""Do the Lamborghini's coated meshes face out? Run through tools/launch_cl_probe.py. For each mesh in a coated DwaMetalMaterial, the
share of its area whose winding normal points away from the car's centre, once its matrix is applied (a low share: faces point
inward, so MoonRay drops the coat there), and whether its matrix mirrors. Writes test-results/car-paint-scene/lambo_winding.json."""
import json
import pathlib
import traceback
import lx

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/car-paint-scene/lambo_winding.json'
report = {}


def world(matrix, p):
    if not matrix:
        return tuple(p)
    return tuple(p[0] * matrix[i] + p[1] * matrix[4 + i] + p[2] * matrix[8 + i] + matrix[12 + i] for i in range(3))


def determinant(m):
    if not m:
        return 1.0
    return (m[0] * (m[5] * m[10] - m[6] * m[9]) - m[1] * (m[4] * m[10] - m[6] * m[8]) + m[2] * (m[4] * m[9] - m[5] * m[8]))


def triple(flat_or_nested):
    if flat_or_nested and not isinstance(flat_or_nested[0], (int, float)):
        return [tuple(v) for v in flat_or_nested]
    return [tuple(flat_or_nested[i:i + 3]) for i in range(0, len(flat_or_nested), 3)]


try:
    from moonray_modo import host
    lx.eval('!scene.open {%s} normal' % (root.parent / 'Downloads/Lamborghini(1)/Lamborghini_Moonray.lxo'))
    snapshot = host.snapshot()
    materials = snapshot.get('materials', {})
    report['paint'] = {k: {'shader': v.get('native_shader'), 'parameters': v.get('native_parameters')} for k, v in materials.items() if v.get('native_shader') == 'DwaMetalMaterial'}
    meshes = snapshot.get('meshes', [])
    report['sample'] = {'faces': str(meshes[0].get('faces'))[:160], 'vertices': str(meshes[0].get('vertices'))[:160], 'matrix': str(meshes[0].get('matrix'))[:160]}
    painted = [m for m in meshes if (materials.get(m.get('material')) or {}).get('native_shader') == 'DwaMetalMaterial']
    placed = []
    for mesh in painted:
        points = [world(mesh.get('matrix'), p) for p in triple(mesh.get('vertices') or [])]
        placed.append((mesh, points))
    every = [p for _, points in placed for p in points]
    centre = tuple((min(p[i] for p in every) + max(p[i] for p in every)) / 2 for i in range(3))
    report['centre'] = centre
    rows = []
    for mesh, points in placed:
        mirrored = determinant(mesh.get('matrix')) < 0
        outward = total = 0.0
        for face in mesh.get('faces') or []:
            a = points[face[0]]
            for i in range(1, len(face) - 1):
                b, c = points[face[i]], points[face[i + 1]]
                u = [b[k] - a[k] for k in range(3)]
                v = [c[k] - a[k] for k in range(3)]
                n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
                area = sum(x * x for x in n) ** .5
                facing = sum(n[k] * (a[k] - centre[k]) for k in range(3))
                total += area
                outward += area if facing > 0 else 0.0
        rows.append({'name': mesh.get('name'), 'material': mesh.get('material'), 'faces': len(mesh.get('faces') or []), 'mirrored': mirrored,
                     'outward': round(outward / total, 3) if total else None, 'area': round(total, 4)})
    report['meshes'] = sorted(rows, key=lambda r: -r['area'])
except Exception:
    report['error'] = traceback.format_exc()
out.write_text(json.dumps(report, indent=1, default=str))
