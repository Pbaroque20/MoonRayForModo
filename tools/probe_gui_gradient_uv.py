# python
"""Modo's Gradient on Texture U and V against Modo's own render, to learn what they are under each projection: a flat
4 x 4 plane (16 x 16 polygons) facing the camera, its UV map "Texture" running 0 to 1 across it (u with x, v with y),
glowing by a Gradient alone (luminous colour, a ramp keyed at -20 and 20, whose evaluated curve is kept). Rendered for:
U and V under the layer's default projection; U with the texture locator moved 1 along x and scaled 2; U and V projected by
the UV map; U projected planar along X, and U and V planar along Z. The scene as the kit captures each is kept too. Writes
test-results/gradient-uv/modo_<case>.exr, <case>.pickle and report.json."""
import json
import pathlib
import pickle
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\gradient-uv')
out.mkdir(parents=True, exist_ok=True)
report = {'cases': {}}
try:
    from moonray_modo import host
    lx.eval('scene.new')
    scene = modo.Scene()
    mesh = scene.addMesh('Plane')
    n = 16
    with mesh.geometry as geo:
        grid = {(i, j): geo.vertices.new((4.0 * i / n - 2.0, 4.0 * j / n - 2.0, 0.0)) for i in range(n + 1) for j in range(n + 1)}
        for i in range(n):
            for j in range(n):
                geo.polygons.new((grid[i, j], grid[i + 1, j], grid[i + 1, j + 1], grid[i, j + 1]))
    geometry = modo.Mesh(mesh).geometry
    uvs = geometry.vmaps.addUVMap('Texture')
    for vertex in geometry.vertices:
        x, y, _ = vertex.position
        uvs[vertex.index] = ((x + 2.0) / 4.0, (y + 2.0) / 4.0)
    geometry.setMeshEdits()
    material = next(i for i in scene.items('advancedMaterial'))
    material.channel('diffAmt').set(0)
    material.channel('specAmt').set(0)
    material.channel('radiance').set(1)
    scene.select(material)
    lx.eval('shader.create gradient')
    gradient = next(i for i in scene.items('gradient'))
    gradient.channel('effect').set('lumiColor')
    for axis in 'RGB':
        # (-20, 20): the gradient's own key at 0 stays, and is given its place on the line.
        for x in (-20.0, 0.0, 20.0):
            lx.eval('channel.key time:%g value:%g channel:{%s:color.%s}' % (x, x + 25.0, gradient.id, axis))
    curve = lx.object.GradientFilter(gradient.channel('color.R').get())
    report['curve'] = [[x / 100.0, curve.Generate(x / 100.0)] for x in range(-2000, 2001)]
    locator = next(i for i in gradient.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
    report['locator'] = {k: locator.channel(k).get() for k in ('projType', 'projAxis', 'uvMap') if locator.channel(k) is not None}
    camera = next(i for i in scene.items('camera'))
    scene.select(camera)
    for name, value in (('pos.X', 0), ('pos.Y', 0), ('pos.Z', 10), ('rot.X', 0), ('rot.Y', 0), ('rot.Z', 0)):
        lx.eval('transform.channel %s %s' % (name, value))
    camera.channel('focalLen').set(0.05)
    camera.channel('apertureX').set(0.036)
    camera.channel('apertureY').set(0.024)
    render = scene.renderItem
    for name, value in (('resX', 384), ('resY', 256), ('first', 1), ('last', 1)):
        render.channel(name).set(value)

    def case(label, param, projection=None, moved=False):
        gradient.channel('param').set(param)
        if projection is not None:
            locator.channel('projType').set(projection)
            if projection == 'uv':
                locator.channel('uvMap').set('Texture')
        scene.select(locator)
        for name, value in (('pos.X', 1 if moved else 0), ('scl.X', 2 if moved else 1), ('scl.Y', 2 if moved else 1), ('scl.Z', 2 if moved else 1)):
            lx.eval('transform.channel %s %s' % (name, value))
        report['cases'][label] = {'param': gradient.channel('param').get(), 'projection': locator.channel('projType').get()}
        snapshot = host.snapshot()
        report['cases'][label]['warnings'] = [w for w in snapshot.get('warnings', []) if 'radient' in w or 'Texture' in w][:3]
        (out / (label + '.pickle')).write_bytes(pickle.dumps(snapshot, protocol=4))
        lx.eval('!render.animation {%s} openexr' % str(out / ('modo_' + label)))
        (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))

    case('u_default', 'textureU')
    case('v_default', 'textureV')
    case('u_moved', 'textureU', moved=True)
    case('u_uv', 'textureU', 'uv')
    case('v_uv', 'textureV', 'uv')
    case('u_planar', 'textureU', 'planar')
    locator.channel('projAxis').set(2)
    case('u_planar_z', 'textureU', 'planar')
    case('v_planar_z', 'textureV', 'planar')
    report['rendered'] = sorted(p.name for p in out.glob('modo_*'))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
