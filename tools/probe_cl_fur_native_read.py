# python
"""Command line: a mesh's fur read by the geometry adapter (fur_reader) against the reading in Python, the same
triangles, normals, materials, maps and guides handed to the grower, and how long each took. Scenes: the guides and
maps scenes of tools/probe_cl_fur_guides.py and probe_cl_fur_maps.py (their Fur set to follow guides, a weight map
and the vector map), and a heavy pelt made here (a sphere of 200,000 polygons). Writes test-results/fur-native-read.json."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results')
result = {}


def captured(scene):
    """What fur_native.grow is handed, once by the adapter and once in Python, with the seconds each reading took."""
    from moonray_modo import extra_geometry, properties, fur_native
    held, taken = fur_native.grow, {}

    def grab(triangles, settings, varied, groups, most=0, runtime=None, guides=None):
        if taken.get('compare', True):
            taken['args'] = (list(triangles), dict(varied), list(groups), [list(map(list, s)) for s in (guides or [])])
        else:
            taken['args'] = None
        # As if grown into no files: only the reading is timed (returning None, the fur is grown in Python after).
        return {'files': {}, 'root': 0.0, 'tip': 0.0, 'wanted': 0, 'grown': 0}
    fur_native.grow = grab
    original = extra_geometry.fur_surface_native
    out = {}
    try:
        for label, native in (('warm', True), ('python', False), ('native', True), ('python2', False), ('native2', True)):
            if not native:
                extra_geometry.fur_surface_native = lambda *a, **k: None
            taken.clear()
            # Compared on the first reading of each kind; timed without the comparison's lists on the others.
            taken['compare'] = label in ('warm', 'python')
            import cProfile, pstats, io
            profile = cProfile.Profile()
            began = time.perf_counter()
            profile.enable()
            extra_geometry.collect(scene, [], properties.scene_settings().get('production', {}))
            profile.disable()
            seconds = round(time.perf_counter() - began, 2)
            stats = pstats.Stats(profile)
            parts = {}
            for (filename, line, name), (_, _, own, total, _) in stats.stats.items():
                if name in ('fur_entries', 'fur_surface_native', 'read', 'collect', 'furs', 'grow', 'kept', 'meshFromMeshChannel'):
                    parts[name + ':' + pathlib.Path(filename).stem] = round(total, 2)
            previous = out.get('python' if label == 'native' else 'warm', (None,))[0] if label in ('native', 'native2', 'python2') else None
            out[label] = (taken.get('args') if taken.get('compare') else previous, seconds, parts)
            extra_geometry.fur_surface_native = original
    finally:
        fur_native.grow, extra_geometry.fur_surface_native = held, original
    return out


def compare(out):
    (a, ta), (b, tb) = out['warm'][:2], out['python'][:2]
    if a is None or b is None:
        return {'error': 'nothing grown', 'seconds': [ta, tb]}
    (tri_a, var_a, grp_a, gd_a), (tri_b, var_b, grp_b, gd_b) = a, b
    gap = 0.0
    for x, y in zip(tri_a, tri_b):
        for p, q in zip(x, y):
            gap = max(gap, max(abs(u - v) for u, v in zip(p, q)))
    maps = {}
    for key in set(var_a) | set(var_b):
        xs, ys = list(var_a.get(key) or []), list(var_b.get(key) or [])
        flat = lambda trio: [v for c in trio for v in (c if isinstance(c, (tuple, list)) else (c,))]
        maps[key] = [len(xs), len(ys), max((abs(u - v) for x, y in zip(xs, ys) for u, v in zip(flat(x), flat(y))), default=0.0)]
    guide_gap = max((abs(u - v) for s, t in zip(gd_a, gd_b) for p, q in zip(s, t) for u, v in zip(p, q)), default=0.0)
    return {'triangles': [len(tri_a), len(tri_b)], 'triangle_gap': gap, 'groups_same': grp_a == grp_b, 'maps': maps,
            'guides': [len(gd_a), len(gd_b)], 'guide_gap': guide_gap,
            'seconds': {k: out[k][1] for k in ('warm', 'native', 'native2', 'python', 'python2')},
            'parts': {k: out[k][2] for k in ('native2', 'python2')}}


try:
    for label, path, setup in (('guides', root / 'fur-guides/guides.lxo', {'guides': 'shape'}),
                               ('maps', root / 'fur-maps/maps.lxo', {'vectorMap': 'FurVector', 'widthMap': 'FurWidth', 'lengthMap': 'FurWidth'})):
        lx.eval('scene.open {%s} normal' % path)
        scene = modo.Scene()
        layer = next(iter(scene.items('furMaterial')))
        for key, value in setup.items():
            layer.channel(key).set(value)
        result[label] = compare(captured(scene))
        lx.eval('!scene.close')
    # A heavy pelt: a sphere of 200,000 polygons wearing a Fur material.
    lx.eval('scene.new')
    scene = modo.Scene()
    lx.eval('item.create mesh Pelt')
    lx.eval('tool.set prim.sphere on')
    for name, value in (('sizeX', 1), ('sizeY', 1), ('sizeZ', 1), ('sides', 500), ('segments', 400)):
        lx.eval('tool.attr prim.sphere %s %s' % (name, value))
    lx.eval('tool.apply'); lx.eval('tool.set prim.sphere off')
    lx.eval('select.type polygon'); lx.eval('select.all')
    lx.eval('poly.setMaterial Pelt {0.5 0.4 0.3} 0.8 0.04 true false')
    lx.eval('select.type item')
    mask = next(m for m in scene.items('mask', superType=False) if m.channel('ptag').get() == 'Pelt')
    lx.eval('select.item {%s} set' % mask.id)
    lx.eval('shader.create furMaterial')
    layer = next(iter(scene.items('furMaterial')))
    layer.channel('dist').set(.01)
    result['pelt'] = compare(captured(scene))
except Exception:
    result['error'] = traceback.format_exc()
(root / 'fur-native-read.json').write_text(json.dumps(result, indent=1, default=str))
