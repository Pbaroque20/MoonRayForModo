# python
"""Command-line test: where MOONRAY_PROBE_SCENE's meshes stand after the root most of them hang from is turned
(transform.channel rot.Y, as probe_fast_moves.py's orbit does): Modo's render cache read anew (evaluated.capture)
against what each item's world matrix says (host.world_matrix, which a move's quick path asks). Where they differ, the
quick path puts the meshes where Modo does not render them. Writes MOONRAY_PROBE_OUT/turn.json."""
import json
import os
import pathlib
import traceback
from collections import Counter
import lx
import modo

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT', 'test-results/cl-export/turn'))
out.mkdir(parents=True, exist_ok=True)
result = {}


def surfaces(data):
    return {(s['source_item'], s.get('instance_index', 0), s['material']): s['matrix'] for s in data['surfaces']}


def far(a, b):
    return max(abs(x - y) for x, y in zip(a, b)) if a and b else None


try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    from moonray_modo import evaluated
    from moonray_modo.host import world_matrix
    scene = modo.Scene()
    roots = Counter()
    for mesh in scene.items('mesh'):
        item = mesh
        while item.parent is not None:
            item = item.parent
        roots[item.id] += 1
    root = scene.item(roots.most_common(1)[0][0])
    result['root'] = {'name': root.name, 'type': root.type}
    time = lx.service.Selection().GetTime()
    before = surfaces(evaluated.capture(time))
    items_before = {key[0]: world_matrix(scene.item(key[0])) for key in before}
    lx.eval('select.item {%s} set' % root.id)
    lx.eval('transform.channel rot.Y 30')
    after = surfaces(evaluated.capture(time))
    items_after = {key[0]: world_matrix(scene.item(key[0])) for key in after}
    result['render_cache_moved'] = sum(1 for k in after if k in before and far(after[k], before[k]) > 1e-4)
    result['items_moved'] = sum(1 for k in items_after if far(items_after[k], items_before.get(k)) > 1e-4)
    result['surfaces'] = len(after)
    # After the turn: whether each surface stands where its item's world matrix says.
    disagree = [k for k in after if far(after[k], items_after[k[0]]) > 1e-4]
    result['surfaces_not_where_their_item_is'] = len(disagree)
    result['example'] = [(k, after[k][12:15], items_after[k[0]][12:15]) for k in disagree[:3]]
    result['root_rotation_channel'] = str(root.channel('rot.Y').get() if root.channel('rot.Y') else None)
    try:
        result['root_rotation'] = float(modo.LocatorSuperType(root).rotation.y.get())
    except Exception as exc:
        result['root_rotation'] = str(exc)
except Exception:
    result['error'] = traceback.format_exc()
(out / 'turn.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
