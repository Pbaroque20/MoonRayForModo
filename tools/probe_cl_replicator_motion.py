# python
"""Command line: PROBE_SCENE read with the shutter's ends, as MoonLightIPR's preview reads it for its motion vectors
(animation.capture_frame with motion, render and realtime readings), reporting what the replicated meshes hold (their
instances and instance identities) and any error. Writes PROBE_OUT/report.json (test-results/replicator/motion)."""
import json
import os
import pathlib
import traceback
import lx

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\replicator\motion'))
out.mkdir(parents=True, exist_ok=True)
result = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def described(scene):
    rows = []
    for mesh in scene.get('meshes') or []:
        ids = mesh.get('instance_ids') or []
        rows.append({'name': mesh.get('name'), 'identity': mesh.get('identity'), 'hidden': mesh.get('hidden'),
                     'instances': len(mesh.get('instances') or []), 'instance_ids': len(ids), 'unique_ids': len(set(map(str, ids))),
                     'first_ids': [str(i) for i in ids[:4]], 'keys': sorted(k for k in mesh if 'instance' in k or 'motion' in k)})
    return rows


try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    from moonray_modo import animation, host, evaluated as evaluated_module
    time = lx.service.Selection().GetTime()
    # Modo's render cache as the kit reads it: each surface's item, prototype, replica index and visibility.
    data = evaluated_module.capture(time)
    result['surfaces'] = [{k: (s.get(k) if k != 'matrix' else [round(v, 3) for v in s.get('matrix', [])[12:15]])
                           for k in ('source_item', 'source_id', 'instance_index', 'instanced', 'visibility', 'layers', 'material', 'matrix')}
                          for s in data['surfaces']]
    result['prototypes'] = {k: [len(seg.get('vertices') or []) for seg in v['segments']] for k, v in data['prototypes'].items()}
    import modo
    result['items'] = [{'name': i.name, 'id': i.id, 'type': i.type, 'visible': str(i.channel('visible').get()) if i.channel('visible') else None,
                        'render': str(i.channel('render').get()) if i.channel('render') else None}
                       for i in modo.Scene().items() if i.type in ('mesh', 'replicator', 'meshInst', 'groupLocator', 'pointCloud') or 'particle' in i.type]
    save()
    for mode, evaluated in (('render', False), ('realtime', True)):
        try:
            result[mode + '_still'] = described(host.snapshot(evaluated_geometry=evaluated))
        except Exception:
            result[mode + '_still_error'] = traceback.format_exc()
        try:
            scene = animation.capture_frame(time, evaluated=evaluated, motion=True, preview=True)
            result[mode + '_motion'] = described(scene)
        except Exception:
            result[mode + '_motion_error'] = traceback.format_exc()
        save()
except Exception:
    result['error'] = traceback.format_exc()
save()
lx.eval('!app.quit')
