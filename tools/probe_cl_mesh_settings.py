# python
"""Command line: the kit's reading of MOONRAY_PROBE_SCENE (host.snapshot, plain or MOONRAY_PROBE_EVALUATED=1), and for
each mesh its subdivision, level, resolution, tessellation and displacement settings as the scene writer gets them,
with the MoonRay object settings of its item. Writes test-results/mesh-settings/<label>.json."""
import json
import os
import pathlib
import traceback
import lx

label = os.environ.get('MOONRAY_PROBE_LABEL', 'scene')
out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\mesh-settings')
out.mkdir(parents=True, exist_ok=True)
result = {}
keys = ('name', 'identity', 'subdivision', 'subdivision_level', 'mesh_resolution', 'adaptive_error', 'ocean_resolution',
        'evaluated_geometry', 'smooth', 'material', 'instances')
try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    from moonray_modo import host, properties
    import modo
    shot = host.snapshot(evaluated_geometry=os.environ.get('MOONRAY_PROBE_EVALUATED') == '1')
    meshes = []
    for mesh in shot.get('meshes') or []:
        entry = {k: (len(mesh[k]) if k == 'instances' and mesh.get(k) else mesh.get(k)) for k in keys}
        entry['faces'] = len(mesh.get('faces') or [])
        try:
            item = modo.Scene().item(mesh.get('identity'))
            entry['moonray_settings'] = {k: v for k, v in (properties.read(item) or {}).items() if not isinstance(v, (dict, list))}
            entry['modo_channels'] = {name: item.channel(name).get() for name in ('psubLevel', 'subdLevel', 'curveRefine', 'render') if item.channel(name)}
        except Exception as exc:
            entry['item_error'] = str(exc)
        meshes.append(entry)
    result['meshes'] = meshes
    result['render'] = {k: v for k, v in (shot.get('render') or {}).items() if not isinstance(v, (dict, list))} if isinstance(shot.get('render'), dict) else None
except Exception:
    result['error'] = traceback.format_exc()
(out / (label + '.json')).write_text(json.dumps(result, indent=1, default=str), encoding='utf-8')
