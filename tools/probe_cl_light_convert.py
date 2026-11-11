# python
"""Command-line: Convert to MoonRay Rect Light (moonray.light.convert). An area light 2 x 0.5, coloured, radiance 3,
turned and moved under a locator, with Visible to Camera on, over a plane. The scene's MoonRay text is written before
and after the conversion, and the light's lines in each kept: what MoonRay is given must be the same light. Also: the
item's name, parent and type after, and that its light material went. Writes test-results/light-convert/report.json."""
import json
import pathlib
import re
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\light-convert')
out.mkdir(parents=True, exist_ok=True)
report = {}


def light_lines():
    from moonray_modo import host, rdla
    snapshot = host.snapshot()
    text = rdla.scene_text(snapshot, 64, 36, 1, 0.0)
    (out / ('scene_%d.rdla' % len(list(out.glob('scene_*.rdla'))))).write_text(text)
    # A Modo light's RectLight is written inside table.insert; a MoonRay item's on its own, then inserted.
    block = re.findall(r'RectLight\("[^"]*"\) \{\n(.*?)\n\}', text, re.S)
    return [dict(re.findall(r'\["([^"]+)"\] = (.*?),?$', b, re.M)) for b in block], snapshot.get('warnings', [])[:5]


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    plane = scene.addMesh('Floor')
    with plane.geometry as geo:
        v = [geo.vertices.new((x, 0.0, z)) for x, z in ((-3, -3), (3, -3), (3, 3), (-3, 3))]
        geo.polygons.new(v)
    rig = scene.addItem('locator', name='Rig')
    rig.position.set((0.5, 0.0, -0.25))
    light = scene.addItem('areaLight', name='Key Area')
    light.setParent(rig)
    light.position.set((0.0, 2.0, 1.0))
    light.rotation.set((-1.1, 0.3, 0.0))
    light.channel('width').set(2.0)
    light.channel('height').set(0.5)
    light.channel('radiance').set(3.0)
    light.channel('visCam').set(1)
    material = next((c for c in light.children() if c.type == 'lightMaterial'), None)
    if material is not None:
        material.channel('lightCol.R').set(1.0)
        material.channel('lightCol.G').set(0.6)
        material.channel('lightCol.B').set(0.3)
    report['before'], report['warnings_before'] = light_lines()
    scene.select(light)
    lx.eval('moonray.light.convert')
    converted = [i for i in modo.Scene().items() if i.name == 'Key Area']
    report['after_items'] = [{'type': i.type, 'parent': i.parent.name if i.parent else None,
                              'children': [c.type for c in i.children()]} for i in converted]
    report['area_lights_left'] = len(list(modo.Scene().items('areaLight')))
    report['after'], report['warnings_after'] = light_lines()
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
