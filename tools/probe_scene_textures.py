# python
"""Isolated GUI test: open a scene (MOONRAY_TEST_SCENE, never saved) and write down what the plugin makes of its
materials' images: each MoonRay material's graph and image file, each mesh's material and UVs, and the notices."""
import json
import os
import pathlib
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/scene-textures'
out.mkdir(parents=True, exist_ok=True)
result = {}
try:
    from moonray_modo import graph_images, host, properties
    path = pathlib.Path(os.environ.get('MOONRAY_TEST_SCENE') or (out / 'scene.txt').read_text().strip())
    lx.eval('scene.open {%s} normal' % path)
    scene = modo.Scene()
    result['scene'] = scene.filename
    held = []
    for item in scene.items('advancedMaterial'):
        settings = properties.read(item)
        if not settings:
            continue
        graph = settings.get('node_graph') or {}
        nodes = graph.get('nodes', {})
        held.append({'item': item.name, 'parent': item.parent.name if item.parent else None, 'shader': settings.get('native_shader'), 'override': settings.get('moonshine_override'),
                     'albedo': graph_images.image(settings, 'albedo'), 'root': graph.get('root'),
                     'nodes': {key: {'type': node.get('type'), 'parameters': node.get('parameters'), 'inputs': node.get('inputs')} for key, node in nodes.items()}})
    result['materials'] = held
    result['masks'] = [[m.name, m.channel('ptyp').get(), m.channel('ptag').get(), m.parent.name if m.parent else None, [t.name + ':' + t.type for t in m.itemGraph('shadeLoc').forward()]]
                       for m in scene.items('mask', superType=False)]
    result['meshes_in_scene'] = [[m.name, len(m.geometry.polygons), [v.name for v in m.geometry.vmaps.uvMaps], sorted({p.materialTag for p in m.geometry.polygons})[:8]] for m in scene.items('mesh', superType=False)]
    taken = host.snapshot(refresh_materials=True)
    result['warnings'] = taken['warnings']
    result['snapshot_materials'] = {key: {'has_png': '.png' in json.dumps(value, default=str).lower(), 'keys': sorted(k for k in value if 'graph' in k or 'native' in k or 'layer' in k or 'shader' in k)}
                                    for key, value in taken['materials'].items()}
    seen = {}
    for mesh in taken['meshes']:
        entry = seen.setdefault((mesh.get('name'), mesh.get('material')), [0, 0, 0])
        entry[0] += 1
        entry[1] += len(mesh.get('faces') or [])
        entry[2] += len(mesh.get('uvs') or [])
    result['snapshot_meshes'] = [[name, material] + counts for (name, material), counts in seen.items()]
    first = next((m for m in taken['meshes'] if m.get('uvs')), None)
    if first:
        result['uv_sample'] = [first.get('uvs')[:4], {k: (v if not isinstance(v, (list, dict)) else str(v)[:200]) for k, v in first.items() if 'uv' in k.lower() and k != 'uvs'}]
    # Were the group the textured material is in for the tag its polygons carry, would the image come through?
    tags = sorted({p.materialTag for m in scene.items('mesh', superType=False) for p in m.geometry.polygons})
    group = next((m for m in scene.items('mask', superType=False) if any(properties.read(c).get('native_shader') for c in m.children() if c.type == 'advancedMaterial')), None)
    if group is not None and tags:
        result['retagged'] = [group.name, group.channel('ptag').get(), tags[0]]
        group.channel('ptag').set(tags[0])
        again = host.snapshot(refresh_materials=True)
        result['retagged_materials'] = {key: '.png' in json.dumps(value, default=str).lower() for key, value in again['materials'].items()}
        result['retagged_warnings'] = again['warnings']
    from moonray_modo import rdla
    text = rdla.scene_text(taken, 320, 180, 2, 0.15, str(out / 'check.exr'))
    (out / 'check.rdla').write_text(text)
    result['rdla_images'] = [line.strip()[:260] for line in text.splitlines() if '.png' in line.lower() or 'ImageMap' in line][:12]
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
