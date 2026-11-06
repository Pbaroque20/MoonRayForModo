# python
"""Command line: a scene's MoonRay materials as the kit holds them (PROBE_SCENE): each material item with a native
shader or node graph, its shader, its parameters, and its graph's nodes (type, parameters, inputs). Writes
PROBE_OUT/materials.json (default test-results/native-materials)."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\native-materials')
out.mkdir(parents=True, exist_ok=True)
result = {}
try:
    lx.eval('scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    scene = modo.Scene()
    from moonray_modo import properties
    for item in scene.iterItems():
        try:
            if not properties.is_material(item):
                continue
            settings = properties.read(item)
        except Exception:
            continue
        if not (settings.get('native_shader') or settings.get('node_graph')):
            continue
        graph = settings.get('node_graph') or {}
        result[item.name] = {'type': item.type, 'id': item.id, 'parent': item.parent.name if item.parent else None,
                             'native_shader': settings.get('native_shader'), 'parameters': settings.get('native_parameters'),
                             'override': settings.get('node_override'), 'root': graph.get('root'),
                             'nodes': {k: {'type': v.get('type'), 'parameters': v.get('parameters'), 'inputs': v.get('inputs')}
                                       for k, v in (graph.get('nodes') or {}).items()}}
except Exception:
    result['error'] = traceback.format_exc()
(out / 'materials.json').write_text(json.dumps(result, indent=1, default=str))
