# python
"""Command-line: Modo's Variation Texture by Mesh Part: a cube whose front face is Part "Lid" and the rest Part "Body",
glowing by the layer; the scene as the kit captures it, with each corner's number. Writes
test-results/variation-part/report.json and part.pickle."""
import json
import pathlib
import pickle
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\variation-part')
out.mkdir(parents=True, exist_ok=True)
report = {}
try:
    from moonray_modo import host
    from moonray_modo.procedurals import VARIATION_PART_MAP
    lx.eval('scene.new')
    scene = modo.Scene()
    mesh = scene.addMesh('Box')
    with mesh.geometry as geo:
        c = [geo.vertices.new((a - .5, b - .5, d - .5)) for a in (0, 1) for b in (0, 1) for d in (0, 1)]
        for index, face in enumerate(((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3))):
            polygon = geo.polygons.new([c[i] for i in face])
            polygon.setTag(lx.symbol.i_POLYTAG_PART, 'Lid' if index == 5 else 'Body')
    material = next(i for i in scene.items('advancedMaterial'))
    material.channel('diffAmt').set(0)
    material.channel('radiance').set(1)
    scene.select(material)
    lx.eval('shader.create variationTexture')
    layer = next(i for i in scene.items('variationTexture'))
    layer.channel('effect').set('lumiColor')
    layer.channel('type').set('meshPart')
    # A ramp from 0 to 1, so that the glow is the part's number.
    for axis in 'RGB':
        for x in (0.0, 1.0):
            lx.eval('channel.key time:%g value:%g channel:{%s:color.%s}' % (x, x, layer.id, axis))
    curve = lx.object.GradientFilter(layer.channel('color.R').get())
    report['curve'] = [[x / 100.0, curve.Generate(x / 100.0)] for x in range(101)]
    snapshot = host.snapshot()
    shaped = snapshot['meshes'][0]
    held = (shaped.get('corner_attributes') or {}).get(VARIATION_PART_MAP)
    report['warnings'] = [w for w in snapshot.get('warnings', []) if 'ariation' in w]
    report['faces'] = [list(shaped['faces'][i]) for i in range(len(shaped['faces']))]
    report['numbers'] = [v[0] for v in held['values']] if held else None
    (out / 'part.pickle').write_bytes(pickle.dumps(snapshot, protocol=4))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
