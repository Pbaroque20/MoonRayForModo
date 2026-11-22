# python
"""Command line: what a scene holds, before any render. PROBE_SCENE the .lxo. For each mesh: points, polygons, its
subdivision, and its vertex maps by kind; every Shader Tree layer under the render item (type, name, effect, enable,
and an image layer's clips with all their channels, a UDIM tile's number among them); each material's displacement
channels and the render item's; then how long host.snapshot takes and what it carries (meshes, attributes, materials,
warnings) and how large the scene comes to for MoonRay (rdla.scene_text, PROBE_SIZE pixels square at PROBE_SAMPLES samples:
64 and 1; PROBE_ALL_MAPS to read and send every weight map, as before host.painted_wanted). Nothing is rendered. Writes
test-results/scene-census/report.json (PROBE_OUT for another folder)."""
import json
import os
import pathlib
import time
import traceback

import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\scene-census'))
out.mkdir(parents=True, exist_ok=True)
report = {}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def channels(item, names=None):
    found = {}
    for name in names or item.channelNames:
        try:
            value = item.channel(name).get()
        except Exception:
            continue
        if value not in (None, ''):
            found[name] = value
    return found


try:
    began = time.perf_counter()
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    report['open_seconds'] = round(time.perf_counter() - began, 2)
    scene = modo.Scene()
    save()

    meshes = []
    for item in scene.items('mesh'):
        entry = {'name': item.name, 'id': item.id}
        try:
            geometry = item.geometry
            entry['points'] = geometry.numVertices
            entry['polygons'] = geometry.numPolygons
            kinds = {}
            for vmap in geometry.vmaps:
                kinds.setdefault(str(vmap.map_type), []).append(vmap.name)
            entry['vmaps'] = {kind: (len(names), names[:8]) for kind, names in kinds.items()}
        except Exception:
            entry['geometry_error'] = traceback.format_exc(limit=1)
        entry['channels'] = channels(item, ('subdivLevel', 'psubLevel', 'curveRefine', 'render', 'visible'))
        meshes.append(entry)
    report['meshes'] = meshes
    report['mesh_totals'] = {'meshes': len(meshes), 'points': sum(m.get('points', 0) for m in meshes),
                             'polygons': sum(m.get('polygons', 0) for m in meshes)}
    save()

    render = scene.renderItem
    report['render'] = channels(render, ('dispRate', 'dispRatio', 'dispJitter', 'dispSmooth', 'dispEdge', 'subdAdapt', 'subdRate',
                                         'resX', 'resY', 'globEnable', 'globLimit', 'aa', 'aaFilter'))
    layers = []

    def walk(item, depth):
        for child in item.children():
            entry = {'depth': depth, 'type': child.type, 'name': child.name,
                     'channels': channels(child, ('enable', 'effect', 'opacity', 'blend', 'invert', 'displace', 'dispVal', 'ptag', 'ptyp',
                                                  'min', 'max', 'swizzling', 'rgba', 'alpha', 'aa', 'textureSize'))}
            if child.type == 'imageMap':
                try:
                    clips = [i for i in child.itemGraph('shadeLoc').forward() if i.type in ('videoStill', 'videoSequence', 'videoClip')]
                    entry['clips'] = [{'type': c.type, 'name': c.name, 'channels': channels(c)} for c in clips]
                    locators = [i for i in child.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator']
                    entry['locator'] = [channels(l, ('projType', 'uvMap', 'tileU', 'tileV', 'wrapU', 'wrapV', 'm00', 'm11', 'udim', 'useUDIM'))
                                        for l in locators]
                except Exception:
                    entry['clip_error'] = traceback.format_exc(limit=1)
            layers.append(entry)
            walk(child, depth + 1)
    walk(render, 0)
    report['layers'] = layers
    report['clips'] = [{'type': c.type, 'name': c.name, 'channels': channels(c)} for t in ('videoStill', 'videoSequence') for c in scene.items(t)]
    save()

    from moonray_modo import host, rdla
    began = time.perf_counter()
    if os.environ.get('PROBE_ALL_MAPS'):
        # Every weight and colour map read and sent, as the kit did before host.painted_wanted.
        from unittest import mock
        with mock.patch.object(host, 'painted_wanted', lambda found: None):
            snapshot = host.snapshot(evaluated_geometry=False)
    else:
        snapshot = host.snapshot(evaluated_geometry=False)
    report['snapshot_seconds'] = round(time.perf_counter() - began, 2)
    shaped = snapshot.get('meshes') or []
    report['snapshot'] = {
        'meshes': len(shaped),
        'points': sum(len(m.get('vertices') or []) for m in shaped),
        'attributes': sorted(set(n for m in shaped for n in list(m.get('point_attributes') or {}) + list(m.get('corner_attributes') or {}))),
        'maps_known': max((len(m.get('_vertex_maps') or []) for m in shaped), default=0),
        'materials': sorted(snapshot.get('materials') or {}),
        'warnings': snapshot.get('warnings') or snapshot.get('_warnings'),
        'mesh_subdivision': [(m.get('name'), m.get('subdivision'), m.get('displacement')) for m in shaped][:40],
    }
    materials = {}
    for tag, material in (snapshot.get('materials') or {}).items():
        rows = []
        for row in material.get('material_stack') or [material]:
            rows.append({'displacement_distance': row.get('displacement_distance'), 'displacement_value': row.get('displacement_value'),
                         'layers': [{k: l.get(k) for k in ('effect', 'kind', 'path', 'color_space', 'srgb', 'tile_u', 'tile_v', 'uv_map', 'opacity', 'enabled', 'error')}
                                    for l in row.get('layers') or []],
                         'errors': row.get('errors') or row.get('layer_errors')})
        materials[tag] = rows
    report['snapshot_materials'] = materials
    save()
    began = time.perf_counter()
    size = int(os.environ.get('PROBE_SIZE', 64))
    from unittest import mock
    from moonray_modo import coordinates
    # PROBE_UV_COPIES: each named UV set written as its own copy, as before coordinates.aliased_keys.
    with mock.patch.object(coordinates, 'aliased_keys', (lambda meshes: frozenset()) if os.environ.get('PROBE_UV_COPIES') else coordinates.aliased_keys):
        text = rdla.scene_text(snapshot, size, size, int(os.environ.get('PROBE_SAMPLES', 1)), 0.0, str(out / 'out.exr'))
    report['rdla'] = {'seconds': round(time.perf_counter() - began, 2), 'bytes': len(text)}
    (out / 'scene.rdla').write_text(text, encoding='utf-8')
except Exception:
    report['error'] = traceback.format_exc()
save()
