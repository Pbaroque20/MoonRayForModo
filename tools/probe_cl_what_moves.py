# python
"""Command line: what moves in a scene around the current frame. PROBE_SCENE the .lxo (the Lamborghini unless named).
Writes test-results/what-moves/<scene stem>.json: the scene's time, frame rate and the camera's shutter; every keyed
channel (an envelope in the edit action), by item; and the world place of every locator-like item (meshes, instances,
locators, the camera) at the frame and at a quarter frame before and after, for those whose place changes."""
import json
import os
import pathlib
import traceback
import lx

scene_path = os.environ.get('PROBE_SCENE', r'C:\Users\Raphael Tobar\Downloads\Lamborghini(1)\Lamborghini_Moonray.lxo')
out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\what-moves'))
out.mkdir(parents=True, exist_ok=True)
report = {'scene': scene_path}


def save():
    (out / (pathlib.Path(scene_path).stem + '.json')).write_text(json.dumps(report, indent=1, default=str))


try:
    lx.eval('!scene.open {%s} normal' % scene_path)
    import modo
    from moonray_modo.host import world_matrix
    scene = modo.Scene()
    selection = lx.service.Selection()
    now = selection.GetTime()
    fps = float(scene.fps)
    report.update(time=now, fps=fps, frame=round(now * fps, 3))
    keyed = []
    read = lx.object.Scene(scene).Channels(lx.symbol.s_ACTIONLAYER_EDIT, 0.0)
    for item in scene.iterItems():
        raw = lx.object.Item(item)
        for index in range(raw.ChannelCount()):
            try:
                if read.IsAnimated(raw, index):
                    keyed.append({'item': item.name, 'type': item.type, 'id': item.id, 'channel': raw.ChannelName(index)})
            except Exception:
                pass
    report['keyed'] = keyed
    # Channel modifiers and what they drive (the first few links of each).
    modifiers = []
    for item in scene.iterItems():
        if not item.type.startswith('cm'):
            continue
        entry = {'item': item.name, 'type': item.type}
        try:
            graph = lx.object.ChannelGraph(lx.object.Scene(scene).GraphLookup(lx.symbol.sGRAPH_CHANMODS))
            raw = lx.object.Item(item)
            drives = []
            for index in range(raw.ChannelCount()):
                for link in range(graph.FwdCount(raw, index)):
                    target, channel = graph.FwdByIndex(raw, index, link)
                    target = lx.object.Item(target)
                    drives.append('%s.%s' % (target.UniqueName(), target.ChannelName(channel)))
            entry['drives'] = drives[:6]
        except Exception as exc:
            entry['drives_error'] = str(exc)[:200]
        if item.type in ('cmRevolve', 'cmColorBlend') or len(modifiers) < 8:
            modifiers.append(entry)
    report['modifiers'] = modifiers
    places = {}
    for item in scene.iterItems():
        if item.type not in ('mesh', 'meshInst', 'locator', 'groupLocator', 'camera'):
            continue
        at = {}
        for label, offset in (('open', -0.25), ('frame', 0.0), ('close', 0.25)):
            selection.SetTime(now + offset / fps)
            at[label] = world_matrix(item)
        selection.SetTime(now)
        if at['open'] != at['close']:
            places[item.name] = {'type': item.type, 'id': item.id,
                                 'translation': {label: [round(v, 4) for v in m[12:15]] for label, m in at.items()},
                                 'rotates': any(abs(a - b) > 1e-6 for a, b in zip(at['open'][:12], at['close'][:12]))}
    report['moving'] = places
    report['moving_count'] = len(places)
except Exception:
    report['error'] = traceback.format_exc()
report['done'] = True
save()
