# python
"""Command line: the third test scene for Shader Tree -> MoonShine (shader_tree_scene): materials whose stack is more than
their own layers over an opaque material, which become graphs of their whole stack. A row of cubes, one material each:
  GroupMask   its group masked by a Group Mask image (the Base Material shows through);
  Opacity     the material at 60% opacity over the Base Material;
  GroupOp     its group at 50% opacity, Multiply;
  Over        a material at 50% opacity in a selection-set mask over this cube's polygons;
  Plain       a colour image only.
And over all of them, a plain group at the top of the Shader Tree holding a stripes image at 40% (layers above their
groups). Images from probe_cl_shader_tree_scene.py's folder. Saved as <out>/round3.lxo. MOONRAY_PROBE_OUT is the folder
(default test-results/shader-tree-round3 in this checkout)."""
import json
import os
import pathlib
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\agent-a1b7a7f9b3e570cb4\test-results')
out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or root / 'shader-tree-round3')
images = pathlib.Path(os.environ.get('MOONRAY_PROBE_IMAGES') or root / 'shader-tree' / 'images')
out.mkdir(parents=True, exist_ok=True)
report = {}
probe = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\agent-a1b7a7f9b3e570cb4\tools\probe_cl_shader_tree_round2.py')
source = probe.read_text(encoding='utf-8')
helpers = source[source.index('def cube('):source.index('\ntry:\n')]
exec(compile(helpers, str(probe), 'exec'))

try:
    lx.eval('scene.new')
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', 1280), ('resY', 360), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    floor = scene.addMesh('Floor')
    with floor.geometry as geo:
        points = [geo.vertices.new(p) for p in ((-8, -.6, -4), (-8, -.6, 4), (8, -.6, 4), (8, -.6, -4))]
        geo.polygons.new(points)
    names = ['GroupMask', 'Opacity', 'GroupOp', 'Over', 'Plain']
    meshes = {}
    for c, name in enumerate(names):
        meshes[name] = cube(name, -3.2 + 1.6 * c, 0.0, name, size=1.0)
    camera = scene.renderCamera
    camera.position.set((0.0, 0.4, 8.5))
    camera.rotation.set((0.0, 0.0, 0.0))
    base = next(i for i in render.children() if i.type == 'advancedMaterial')
    base.channel('diffCol.R').set(.2)
    base.channel('diffCol.G').set(.7)
    base.channel('diffCol.B').set(.9)
    # GroupMask: a colour image, the group masked by a Group Mask image.
    mask = mask_of('GroupMask')
    layer(mask, 'imageMap', 'diffColor', images / 'colour.png')
    layer(mask, 'imageMap', 'groupMask', images / 'grey.png')
    # Opacity: the material at 60%.
    material_in(mask_of('Opacity')).channel('opacity').set(.6)
    layer(mask_of('Opacity'), 'imageMap', 'diffColor', images / 'colour.png')
    # GroupOp: the group at 50%, Multiply.
    group = mask_of('GroupOp')
    group.channel('opacity').set(.5)
    group.channel('blend').set('multiply')
    layer(group, 'imageMap', 'diffColor', images / 'stripes.png')
    # Over: its own image, and a selection-set mask over its polygons holding a material at 50% (above the cubes' masks).
    layer(mask_of('Over'), 'imageMap', 'diffColor', images / 'green.png')
    lx.eval('select.item {%s} set' % meshes['Over'].id)
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('select.editSet OverSet add')
    lx.eval('select.type item')
    over = scene.addItem('mask')
    shader = next(i for i in render.children() if i.type == 'defaultShader')
    over.setParent(render, max(0, shader.parentIndex - 1))
    over.channel('ptyp').set('Selection Set')
    over.channel('ptag').set('OverSet')
    over.name = 'OverSet mask'
    upper = scene.addItem('advancedMaterial')
    upper.setParent(over, 0)
    upper.name = 'Over50'
    upper.channel('opacity').set(.5)
    for axis, value in zip('RGB', (.9, .9, .1)):
        upper.channel('diffCol.' + axis).set(value)
    layer(over, 'imageMap', 'diffColor', images / 'dots.png')
    # Plain.
    layer(mask_of('Plain'), 'imageMap', 'diffColor', images / 'colour.png')
    # Above all the cubes' groups: a plain group holding stripes at 40%.
    top = scene.addItem('mask')
    shader = next(i for i in render.children() if i.type == 'defaultShader')
    top.setParent(render, max(0, shader.parentIndex - 1))
    top.name = 'Wear group'
    wear, _ = layer(top, 'imageMap', 'diffColor', images / 'stripes.png')
    wear.channel('opacity').set(.4)
    report['children'] = [(i.name, i.type) for i in reversed(list(render.children()))]
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'round3.lxo'))
    report['saved'] = str(out / 'round3.lxo')
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report-scene.json').write_text(json.dumps(report, indent=1, default=str))
