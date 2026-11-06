# python
"""Command line: a scene for the report that a DwaSkinMaterial sends XPU2 back to XPU. A sphere on a floor wearing a
MoonShine material whose shader is DwaSkinMaterial at its own defaults, as one is made in Modo. Saved as
test-results/skin-xpu2/skin.lxo for tools/probe_mesh_light_all_engines.py (PROBE_SCENE, MOONRAY_PROBE_NO_MODO); the
material's settings as the kit holds them are in report.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\skin-xpu2')
out.mkdir(parents=True, exist_ok=True)
report = {}
try:
    lx.eval('scene.new')
    scene = modo.Scene()
    floor = scene.addMesh('Floor')
    with floor.geometry as geo:
        points = [geo.vertices.new(p) for p in ((-4, 0, -4), (-4, 0, 4), (4, 0, 4), (4, 0, -4))]
        geo.polygons.new(points)
    lx.eval('item.create mesh Ball')
    ball = next(i for i in scene.items('mesh') if i.name.startswith('Ball'))
    lx.eval('select.item {%s} set' % ball.id)
    lx.eval('tool.set prim.sphere on')
    for key, value in (('cenY', 0.6), ('sizeX', 0.6), ('sizeY', 0.6), ('sizeZ', 0.6), ('sides', 48), ('segments', 24)):
        lx.eval('tool.attr prim.sphere %s %s' % (key, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    lx.eval('select.type item')
    lx.eval('select.item {%s} set' % ball.id)
    from moonray_modo import materials, nodes, properties
    from moonray_modo.material_override import synchronize
    material = materials.assign(kind='material.moonrayMoonShine', name='Skin')
    if material is None:
        material = next(i for i in scene.iterItems() if i.type == 'material.moonrayMoonShine')
    graph = nodes.new('DwaSkinMaterial')
    settings = properties.read(material)
    settings.update(native_shader='DwaSkinMaterial', node_graph=graph, node_override=True)
    properties.write(material, synchronize(settings, graph))
    report['settings'] = {k: v for k, v in properties.read(material).items() if k != 'node_graph'}
    report['graph'] = graph
    camera = scene.renderCamera
    camera.position.set((0.0, 1.0, 3.5))
    camera.rotation.set((-0.12, 0.0, 0.0))
    render = scene.renderItem
    for name, value in (('resX', 480), ('resY', 320), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'skin.lxo'))
    report['saved'] = True
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
