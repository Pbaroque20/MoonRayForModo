# python
"""Modo's Gradient on Clip Distance against Modo's own render: three planes facing the camera at 2, 6 and 10 units from
it, side by side, glowing by the Gradient alone (luminous colour, a ramp keyed -100, 0 and 100 to the same values, whose
curve is kept), with the camera's clipping off and on, at clip distances 4 and 8. Writes
test-results/gradient-clip/modo_<case>.exr and report.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\gradient-clip')
out.mkdir(parents=True, exist_ok=True)
report = {'cases': {}}
CAMERA_Z = 10.0
DEPTHS = (2.0, 6.0, 10.0)

try:
    for case, clipping, clip in (('off4', 0, 4.0), ('on4', 1, 4.0), ('on8', 1, 8.0), ('on1', 1, 1.0)):
        try:
            lx.eval('scene.new')
            scene = modo.Scene()
            mesh = scene.addMesh('Planes')
            with mesh.geometry as geo:
                for k, depth in enumerate(DEPTHS):
                    z = CAMERA_Z - depth
                    s = depth * 0.12
                    cx = (k - 1) * depth * 0.24
                    v = [geo.vertices.new((cx + a * s, b * s, z)) for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
                    geo.polygons.new(v)
            material = next(i for i in scene.items('advancedMaterial'))
            for name, value in (('diffAmt', 0), ('specAmt', 0), ('radiance', 1)):
                material.channel(name).set(value)
            scene.select(material)
            lx.eval('shader.create gradient')
            gradient = next(i for i in scene.items('gradient'))
            gradient.channel('effect').set('lumiColor')
            gradient.channel('param').set('clipDist')
            for axis in 'RGB':
                for x in (-100.0, 0.0, 100.0):
                    lx.eval('channel.key time:%g value:%g channel:{%s:color.%s}' % (x, x, gradient.id, axis))
            curve = lx.object.GradientFilter(gradient.channel('color.R').get())
            report['curve'] = [[x / 100.0, curve.Generate(x / 100.0)] for x in range(-10000, 10001, 5)]
            camera = next(i for i in scene.items('camera'))
            scene.select(camera)
            for name, value in (('pos.X', 0), ('pos.Y', 0), ('pos.Z', CAMERA_Z), ('rot.X', 0), ('rot.Y', 0), ('rot.Z', 0)):
                lx.eval('transform.channel %s %s' % (name, value))
            camera.channel('clipping').set(clipping)
            camera.channel('clipDist').set(clip)
            report['cases'][case] = {k: camera.channel(k).get() for k in ('clipping', 'clipDist', 'focalLen', 'apertureX', 'apertureY')}
            render = scene.renderItem
            for name, value in (('resX', 240), ('resY', 80), ('first', 1), ('last', 1)):
                render.channel(name).set(value)
            lx.eval('!render.animation {%s} openexr' % str(out / ('modo_' + case)))
        except Exception:
            report['cases'][case] = {'error': traceback.format_exc()}
        (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
