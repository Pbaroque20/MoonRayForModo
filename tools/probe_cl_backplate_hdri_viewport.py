# python
"""Command line: a Backplate's HDRI in Modo's viewport (backplate_viewport: the kit's viewport environment). A new
scene; a Backplate given an HDRI (PROBE_HDRI); moonray.backplate.viewport run by hand (no Qt timers here) after each
step: made; HDRI Rotation 90 (the layer's Texture Locator turned); "HDRI in the viewport" off (taken away) and on again;
the Backplate deleted (taken away). At each step: the kit's environments (tags, layer, clip, locator projection, axis
and world matrix) and what a render reads of the scene's environments (host.snapshot: the viewport one must not be
among them). Writes PROBE_OUT/report.json. Run: tools/launch_cl_probe.py probe_cl_backplate_hdri_viewport.py."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\backplate-hdri-viewport'))
out.mkdir(parents=True, exist_ok=True)
HDRI = os.environ['PROBE_HDRI']
report = {'stages': []}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def stage(name):
    from moonray_modo import backplate_viewport, host
    scene = modo.Scene()
    found = []
    for item in scene.items('environment'):
        entry = {'id': item.id, 'name': item.name, 'owner': backplate_viewport._tag(item, backplate_viewport.OWNER),
                 'shown': backplate_viewport._tag(item, backplate_viewport.SHOWN), 'parent': item.parent.type if item.parent else None,
                 'index': [c.id for c in scene.renderItem.children()].index(item.id) if item.parent else None,
                 'children': [(c.type, c.name) for c in item.children()]}
        for layer in item.children():
            if layer.type != 'imageMap':
                continue
            loc = next((i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator'), None)
            clip = next((i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'videoStill'), None)
            entry['layer'] = {'effect': layer.channel('effect').get(), 'clip': clip.channel('filename').get() if clip else None,
                              'projType': loc.channel('projType').get() if loc else None,
                              'projAxis': loc.channel('projAxis').get() if loc else None,
                              'matrix': [round(v, 4) for v in host.world_matrix(loc)] if loc else None}
        found.append(entry)
    snap = host.snapshot()
    report['stages'].append({'stage': name, 'environments': found, 'lacking': backplate_viewport.lacking(scene),
                             'rendered': [(e.get('name'), e.get('kind'), e.get('identity')) for e in snap.get('environments') or []],
                             'txtrLocators': len(list(scene.items('txtrLocator')))})
    save()


def channel(key, value):
    from moonray_modo import entities
    lx.eval('select.item {%s} set' % report['plate'])
    lx.eval('item.channel %s$%s%s %s' % (entities.item_type('BackplateEnvironment'), entities.CHANNEL_PREFIX, key, value))


try:
    from moonray_modo import entities
    lx.eval('scene.new')
    lx.eval('moonray.entity.add BackplateEnvironment')
    scene = modo.Scene()
    report['plate'] = [i for i in scene.items() if i.type == entities.item_type('BackplateEnvironment')][0].id
    report['before'] = len(list(scene.items('txtrLocator')))
    lx.eval('moonray.backplate.viewport')
    stage('added, no HDRI')
    channel('hdri', '{%s}' % HDRI)
    lx.eval('moonray.backplate.viewport')
    stage('HDRI given')
    channel('hdri_rotation', '90')
    lx.eval('moonray.backplate.viewport')
    stage('rotation 90')
    channel('hdri_rotation', '-30')
    lx.eval('moonray.backplate.viewport')
    stage('rotation -30')
    channel('viewport_hdri', 'false')
    lx.eval('moonray.backplate.viewport')
    stage('viewport HDRI off')
    channel('viewport_hdri', 'true')
    lx.eval('moonray.backplate.viewport')
    stage('on again')
    lx.eval('select.item {%s} set' % report['plate'])
    lx.eval('!item.delete')
    lx.eval('moonray.backplate.viewport')
    stage('backplate deleted')
    report['faults'] = dict(entities.DRAW_FAULTS)
except Exception:
    report['error'] = traceback.format_exc()
save()
