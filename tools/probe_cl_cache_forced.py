# python
"""Command-line test: Modo's render cache read the old way (made, then updated forced: two evaluations) and the new way
(made, updated only for another time: one), on MOONRAY_PROBE_SCENE as opened, after one mesh's points are moved, and at
another moment: the same surfaces, places and geometry both ways, and how long each took. Writes
MOONRAY_PROBE_OUT/forced.json."""
import json
import os
import pathlib
import time as clock
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT', 'test-results/cl-export/forced'))
out.mkdir(parents=True, exist_ok=True)
result = {}


def fingerprint(data):
    """Each surface (item, instance, material: its matrix) and each prototype's segments' lists, as digests."""
    from moonray_modo.scene_digest import content
    surfaces = {(s['source_item'], s.get('instance_index', 0), s['material'], s.get('part', '')): content(s['matrix'])
                for s in data['surfaces']}
    prototypes = {}
    for key, held in data['prototypes'].items():
        prototypes[(held.get('item'), held.get('material'), held.get('part'))] = [
            tuple(content(segment.get(name)) if segment.get(name) is not None else '' for name in ('vertices', 'faces', 'normals'))
            for segment in held.get('segments', [])]
    return surfaces, prototypes


def compare(name, at):
    from moonray_modo import evaluated
    bridge = evaluated._load()
    readings = {}
    for way, forced in (('old', 1), ('new', 0)):
        bridge.MR_geometry_forced(forced)
        began = clock.perf_counter()
        data = evaluated.capture(at)
        readings[way] = (round(clock.perf_counter() - began, 2), fingerprint(data))
    (old_time, (old_s, old_p)), (new_time, (new_s, new_p)) = readings['old'], readings['new']
    result[name] = {'old_seconds': old_time, 'new_seconds': new_time, 'surfaces': len(new_s),
                    'surfaces_differ': sorted(str(k) for k in set(old_s) ^ set(new_s))[:3] + [str(k) for k in old_s if k in new_s and old_s[k] != new_s[k]][:3],
                    'prototypes_differ': [str(k) for k in set(old_p) | set(new_p) if old_p.get(k) != new_p.get(k)][:5]}
    bridge.MR_geometry_forced(0)
    return readings


try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    time = lx.service.Selection().GetTime()
    compare('as opened', time)
    compare('as opened, again', time)
    meshes = sorted(((len(modo.Mesh(m).geometry.vertices), m) for m in modo.Scene().items('mesh')), key=lambda e: e[0])
    chosen = next((m for n, m in meshes if n >= 4000), meshes[-1][1])
    before = compare('before the edit', time)
    lx.eval('select.item {%s} set' % chosen.id)
    lx.eval('select.typeFrom vertex')
    lx.eval('select.drop vertex')
    lx.eval('tool.set TransformMove on')
    lx.eval('tool.attr xfrm.transform TY 0.05')
    lx.eval('tool.doApply')
    lx.eval('tool.set TransformMove off')
    lx.eval('select.typeFrom item')
    after = compare('after a mesh edit', time)
    # The edit is in the new way's reading: the edited mesh's prototype differs from before it.
    old_p, new_p = before['new'][1][1], after['new'][1][1]
    result['edit seen by the new way'] = [str(k) for k in new_p if k[0] == chosen.id and old_p.get(k) != new_p.get(k)][:3]
    compare('another moment', time + 1.0 / 24.0)
except Exception:
    result['error'] = traceback.format_exc()
(out / 'forced.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
