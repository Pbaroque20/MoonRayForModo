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
    index = len(list(out.glob('scene_*.rdla')))
    (out / ('scene_%d.rdla' % index)).write_text(text)
    # The capture itself too, for tools/make_readme_images_1111.py to render (before, then after).
    import pickle
    (out / ('scene_%d.pickle' % index)).write_bytes(pickle.dumps(snapshot, protocol=4))
    # A Modo light's RectLight is written inside table.insert; a MoonRay item's on its own, then inserted.
    block = re.findall(r'RectLight\("[^"]*"\) \{\n(.*?)\n\}', text, re.S)
    return [dict(re.findall(r'\["([^"]+)"\] = (.*?),?$', b, re.M)) for b in block], snapshot.get('warnings', [])[:5]


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    # The new scene's own sun taken away: the area light lights it alone.
    for sun in list(scene.items('sunLight')):
        scene.removeItems(sun)
    # And the sky made black, so that what is lit is lit by the area light.
    for material in scene.items('envMaterial'):
        for name in ('zenColor', 'skyColor', 'gndColor', 'nadColor'):
            for axis in 'RGB':
                held = material.channel('%s.%s' % (name, axis))
                if held is not None:
                    held.set(0.0)
    camera = next(i for i in scene.items('camera'))
    camera.position.set((0.0, 3.0, 6.5))
    camera.rotation.set((-0.42, 0.0, 0.0))
    plane = scene.addMesh('Floor')
    with plane.geometry as geo:
        v = [geo.vertices.new((x, 0.0, z)) for x, z in ((-3, -3), (3, -3), (3, 3), (-3, 3))]
        geo.polygons.new(v)
    box = scene.addMesh('Box')
    with box.geometry as geo:
        c = [geo.vertices.new((a - .5, b, d - .5)) for a in (0, 1) for b in (0, 1) for d in (0, 1)]
        for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            geo.polygons.new([c[i] for i in face])
    rig = scene.addItem('locator', name='Rig')
    rig.position.set((0.5, 0.0, -0.25))
    light = scene.addItem('areaLight', name='Key Area')
    light.setParent(rig)
    light.position.set((0.0, 2.0, 1.0))
    light.rotation.set((-1.1, 0.3, 0.0))
    light.channel('width').set(2.0)
    light.channel('height').set(0.5)
    light.channel('radiance').set(12.0)
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
