# python
"""Command-line test: a saved scene's materials as MoonLightIPR receives them (MOONRAY_PROBE_SCENE, opened and never
saved). The scene is captured as the preview captures it and packed for MoonLightIPR with the installed runtime; the
report gives each material's colour, layers and images, which meshes wear it, what packing says, and the snapshot itself
(snapshot.json) for tools/compare_moonlightipr.py to render in MoonRay and MoonLightIPR side by side.
Written to test-results/scene-materials."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\scene-materials')
out.mkdir(parents=True, exist_ok=True)
result = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def brief(layer):
    keep = ('kind', 'effect', 'path', 'srgb', 'color_space', 'opacity', 'blend', 'invert', 'color', 'value', 'image_channel',
            'gamma', 'low', 'high', 'uv_map', 'projection', 'enabled', 'alpha', 'tile_u', 'tile_v', 'bias', 'gain')
    return {k: layer[k] for k in keep if k in layer}


try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    from moonray_modo import host, native, moonlightipr_scene
    snapshot = host.snapshot()
    wearers = {}
    for mesh in snapshot.get('meshes', []):
        for tag in set(mesh.get('face_materials') or [mesh.get('material', '')]):
            wearers.setdefault(tag, set()).add(str(mesh.get('name')))
    result['materials'] = {}
    for tag, material in snapshot.get('materials', {}).items():
        layers = material.get('layers')
        result['materials'][tag] = {
            'worn_by': sorted(wearers.get(tag, []))[:6],
            'values': {k: material.get(k) for k in ('name', 'shader', 'native_shader', 'color', 'raw_color', 'diffuse_amount', 'metallic',
                                                    'roughness', 'specular_amount', 'transmission', 'clearcoat', 'standard_material')},
            'layers': [brief(layer) for layer in layers] if layers else None,
            'textures': {k: brief(v) for k, v in (material.get('textures') or {}).items()},
            'graph': bool(material.get('node_graph'))}
    save()
    runtime = native.find_runtime(native.default_runtime())
    result['runtime'] = str(runtime)
    try:
        payload, keys, warnings = moonlightipr_scene.pack(snapshot, 320, 180, 0.15, (), 16, False, runtime)
        result['pack'] = {'bytes': len(payload), 'warnings': warnings}
    except Exception:
        result['pack'] = {'error': traceback.format_exc()[-2000:]}
    for key in [k for k in snapshot if k.startswith('_')]:
        snapshot.pop(key)
    (out / 'snapshot.json').write_text(json.dumps(snapshot, default=str))
except Exception:
    result['error'] = traceback.format_exc()
save()
