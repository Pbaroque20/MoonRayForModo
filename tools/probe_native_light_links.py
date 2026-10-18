# python
"""Isolated GUI test: Modo's own light linking (a light's Light Linking group, include or exclude) against MoonRay.

Two squares side by side facing the camera, lit only by Modo's directional light; the environment is black. The light
is linked to a group holding the left square, set first to exclude it and then to include it. For each, Modo's own
render is saved (modo_<case>) and the scene exported for MoonRay (<case>.rdla); tools/check_native_light_links.py
renders those and compares each square's brightness. Noted: how the link was made, and the plugin's warnings."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/native-light-links'
out.mkdir(parents=True, exist_ok=True)
result = {'cases': {}}
SIZE = (160, 80)


def square(scene, name, x):
    mesh = scene.addMesh(name)
    with mesh.geometry as g:
        corners = [g.vertices.new((x + a, b, 0.0)) for a, b in ((-.8, -.8), (.8, -.8), (.8, .8), (-.8, .8))]
        g.polygons.new(corners)
    return mesh


try:
    from moonray_modo import host, rdla
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', SIZE[0]), ('resY', SIZE[1]), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    environment = next(iter(scene.items('environment')))
    environment.channel('radiance').set(0.0)
    camera = scene.renderCamera
    camera.position.set((0, 0, 4.0))
    camera.rotation.set((0, 0, 0), degrees=True)
    left, right = square(scene, 'Left', -1.0), square(scene, 'Right', 1.0)
    light = next(iter(scene.items('sunLight')))
    lx.eval('select.item {%s} set' % light.id)
    lx.eval('transform.channel rot.X 0.0')
    lx.eval('transform.channel rot.Y 0.0')
    lx.eval('transform.channel rot.Z 0.0')
    group = scene.addGroup('LeftOnly')
    group.addItems(left)
    # The light's Light Linking group: a link in its shading graph to the group.
    try:
        lx.object.ItemGraph(lx.object.Scene(scene).GraphLookup('shadeLoc')).AddLink(light, group)
        result['link'] = 'ItemGraph.AddLink'
    except Exception as exc:
        result['link_error'] = str(exc)
        lx.eval('item.link shadeLoc {%s} {%s}' % (light.id, group.id))
        result['link'] = 'item.link'
    result['linked'] = [item.name for item in light.itemGraph('shadeLoc').forward()]
    light.channel('linkEnable').set(True)
    # Each step of the plugin's capture, for this light.
    try:
        from moonray_modo import native_light_links
        from moonray_modo.host import channel
        listed = [(item.name, item.type) for item in scene.items('light')]
        forward = [(v.name, v.type) for v in light.itemGraph('shadeLoc').forward()]
        result['capture_steps'] = {'lights_listed': listed, 'linkEnable': channel(light, 'linkEnable', False),
                                   'linkMode': channel(light, 'linkMode', 'include'), 'forward': forward,
                                   'members': native_light_links.linked_members(light), 'left': left.id}
    except Exception:
        result['capture_steps_error'] = traceback.format_exc()
    for case, mode in (('exclude', 'exclude'), ('include', 'include')):
        entry = {}
        try:
            light.channel('linkMode').set(mode)
            entry['mode'] = light.channel('linkMode').get()
            lx.eval('!render.animation {%s} openexr' % str(out / ('modo_' + case)))
            snapshot = host.snapshot()
            entry['links'] = snapshot.get('native_light_links')
            entry['warnings'] = [w for w in snapshot.get('warnings', []) if 'renderOutput' not in w][:6]
            (out / (case + '.rdla')).write_text(rdla.scene_text(snapshot, SIZE[0], SIZE[1], 4, 0.0, str(out / ('moonray_' + case + '.exr'))), encoding='utf-8')
        except Exception:
            entry['error'] = traceback.format_exc()
        result['cases'][case] = entry
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
