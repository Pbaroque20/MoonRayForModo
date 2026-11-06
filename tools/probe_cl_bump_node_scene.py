# python
"""Command line: a scene for the node graph's Bump node. Two spheres on a floor, lit by a directional light from
the side: the left one a MoonShine material whose graph runs a checker height image (test-results/bump-node/
height.png, made beforehand) through a Bump node (amplitude 0.01) into its normal; the right one the same material
with the image on its colour alone and no bump, for comparison. Saved as test-results/bump-node/bump_node.lxo for
tools/probe_mesh_light_all_engines.py (PROBE_SCENE, MOONRAY_PROBE_NO_MODO)."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\bump-node')
report = {}


def sphere(name, x):
    lx.eval('item.create mesh {%s}' % name)
    mesh = next(i for i in modo.Scene().items('mesh') if i.name == name)
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('tool.set prim.sphere on')
    for key, value in (('cenX', x), ('cenY', 0.6), ('sizeX', 0.6), ('sizeY', 0.6), ('sizeZ', 0.6), ('sides', 48), ('segments', 24)):
        lx.eval('tool.attr prim.sphere %s %s' % (key, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    lx.eval('select.type item')
    return mesh


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    floor = scene.addMesh('Floor')
    with floor.geometry as geo:
        points = [geo.vertices.new(p) for p in ((-4, 0, -4), (-4, 0, 4), (4, 0, 4), (4, 0, -4))]
        geo.polygons.new(points)
    from moonray_modo import materials, nodes, properties
    from moonray_modo.material_override import synchronize
    height = str(out / 'height.png')
    made = {}
    for name, x, bumped in (('Bumped', -0.75, True), ('Smooth', 0.75, False)):
        mesh = sphere(name, x)
        lx.eval('select.item {%s} set' % mesh.id)
        material = materials.assign(kind='material.moonrayMoonShine', name=name + ' Shine')
        if material is None:
            material = next(i for i in scene.iterItems() if i.type == 'material.moonrayMoonShine' and i.id not in made.values())
        made[name] = material.id
        graph = nodes.new()
        graph['nodes']['img'] = {'type': 'image', 'parameters': {'file': height, 'srgb': False, 'uv_map': 'Texture', 'scale': [1, 1]}, 'inputs': {}}
        graph['nodes']['tint'] = {'type': 'mix', 'parameters': {'bg': [.6, .3, .2], 'fg': [.8, .7, .5], 'mix': .5}, 'inputs': {'mix': 'img'}}
        graph['nodes']['surface']['inputs']['albedo'] = 'tint'
        if bumped:
            graph['nodes']['bump'] = {'type': 'bump', 'parameters': {'amplitude': 0.01, 'step': 0.0}, 'inputs': {'height': 'img'}}
            graph['nodes']['surface']['inputs']['input_normal'] = 'bump'
        settings = properties.read(material)
        settings.update(native_shader=graph['nodes'][graph['root']]['type'], node_graph=graph, node_override=True)
        properties.write(material, synchronize(settings, graph))
    report['materials'] = made
    camera = scene.renderCamera
    camera.position.set((0.0, 1.0, 4.0))
    camera.rotation.set((-0.12, 0.0, 0.0))
    light = next(iter(scene.items('sunLight')), None)
    if light is not None:
        light.rotation.set((-0.5, 1.2, 0.0))
    render = scene.renderItem
    for name, value in (('resX', 640), ('resY', 360), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'bump_node.lxo'))
    report['saved'] = True
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
