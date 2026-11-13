# python
"""Command line: a scene's displacement as each engine is given it. PROBE_SCENE the .lxo. For each material: its graph's
displacement node and what feeds it, its Shader Tree displacement layers, and MoonLightIPR's program for it
(moonlightipr_materials.displacement_tree, with what it leaves out); for each mesh, its triangles and the material
tags it wears. Writes test-results/displacement-dump/report.json."""
import json
import os
import pathlib
import traceback
import lx

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\displacement-dump')
out.mkdir(parents=True, exist_ok=True)
report = {}
try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    from moonray_modo import host, scene_setup, nodes, ocean, face_tags
    from moonray_modo import moonlightipr_materials as mm
    scene = host.snapshot()
    scene_setup.configure(scene, scene_setup.values())
    materials = {}
    with ocean.writing(float(scene.get('time') or 0.0)):
        for tag, material in (scene.get('materials') or {}).items():
            entry = {}
            for row in material.get('material_stack') or [material]:
                graph = row.get('node_graph')
                if graph:
                    entry['displacement'] = graph.get('displacement')
                    entry['nodes'] = {k: {'type': v.get('type'), 'inputs': v.get('inputs'),
                                          'parameters': {p: v.get('parameters', {}).get(p) for p in
                                                         ('factor', 'source_space', 'tangent_space_style', 'height', 'bound_padding', 'texture')
                                                         if p in (v.get('parameters') or {})}}
                                      for k, v in graph.get('nodes', {}).items()}
                    entry['node_override'] = row.get('node_override')
                    entry['native_shader'] = row.get('native_shader')
                layers = row.get('layers') or []
                entry['displace_layers'] = [{k: l.get(k) for k in ('effect', 'kind', 'path')} for l in layers if 'disp' in str(l.get('effect'))]
                entry['displacement_distance'] = row.get('displacement_distance')
            notes = []
            from moonray_modo import native
            found = mm.displacement_tree(material, notes.append, native.default_runtime())
            entry['runtime'] = str(native.default_runtime())
            entry['program'] = found[1] if found else None
            entry['leaf_layers'] = [[l.get('effect') for l in leaf[2]] for leaf in found[0]] if found else None
            entry['left_out'] = notes
            entry['mesh_program'] = mm.displacement(material)
            materials[tag] = entry
    report['materials'] = materials
    report['meshes'] = [{'name': m.get('name'), 'faces': len(m.get('faces') or []), 'tags': sorted(face_tags.worn(m)),
                         'uvs': bool(m.get('uvs')), 'subdivision': m.get('subdivision')} for m in scene.get('meshes', [])]
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
