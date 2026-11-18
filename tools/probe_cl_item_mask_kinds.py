# python
"""Command-line test: group masks naming an item that is not a mesh, as Modo renders them and as the plugin reads them.
Ten cubes in a row, each but the last in a group mask of its own (Polygon Tag Type Material, Polygon Tag (all), as
Add Layer > Group makes one) that holds a Material of its own colour:
- Locator (red): the cube under a plain Locator, the mask naming the locator;
- Nested (magenta): under a Locator under a Locator, the mask naming the outer one;
- Group Locator (green): under a Group Locator, the mask naming it;
- Group (blue): the cube in a Group of the Groups list, the mask naming the group;
- Sub-group (cyan): the cube in a Group inside another, the mask naming the outer one, Apply to Sub-Group off;
- Sub-group applied (orange): the same, Apply to Sub-Group on;
- Group of a locator (purple): under a Group Locator that is in a Group, the mask naming the group;
- Group of a plain locator (azure): under a plain Locator that is in a Group, the mask naming the group;
- Mesh (yellow): the mask naming the cube itself;
- Other: in no mask (Base Material).
Writes test-results/item-mask-kinds: item_masks.lxo, modo.*.exr (Modo's render), masks.rdla (the plugin's export made
in the same reading; tools/probe_cl_item_mask_stacks.py exports it again from the scene reopened, for
tools/check_item_mask_kinds.py) and report.json (what was built, how each mask is linked, the mask's channels and how
a group holds its members)."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\item-mask-kinds')
out.mkdir(parents=True, exist_ok=True)
for old in out.glob('*'):
    old.unlink()
report = {'steps': [], 'masks': {}}
# Masks are made bottom to top in this order: those naming a plain locator first, which Modo treats as naming nothing
# (they go over every surface), so that they cover none of the others. tools/check_item_mask_kinds.py has the same.
CUBES = (('Locator', (1, 0, 0)), ('Nested', (1, 0, 1)), ('Group Locator', (0, 1, 0)), ('Group', (0, 0, 1)),
         ('Sub-group', (0, 1, 1)), ('Sub-group applied', (1, .5, 0)), ('Group of a locator', (.5, 0, 1)),
         ('Group of a plain locator', (0, .5, 1)), ('Mesh', (1, 1, 0)), ('Other', None))
SPACING = 1.2


def step(name, command):
    try:
        lx.eval(command)
        report['steps'].append([name, 'ok'])
        return True
    except Exception as exc:
        report['steps'].append([name, 'failed: %s' % exc])
        return False


def cube(name, x):
    lx.eval('item.create mesh')
    mesh = modo.Scene().selected[-1]
    mesh.name = name
    lx.eval('tool.set prim.cube on')
    for attribute, value in (('cenX', x), ('cenY', 0), ('cenZ', 0), ('sizeX', .8), ('sizeY', .8), ('sizeZ', .8),
                             ('segmentsX', 1), ('segmentsY', 1), ('segmentsZ', 1), ('radius', 0)):
        try:
            lx.eval('tool.attr prim.cube %s %s' % (attribute, value))
        except Exception:
            pass
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    return mesh


def link(mask, target):
    """The mask named for target: Modo's own command first (it takes the item's name), else the graph."""
    linked = lambda: [i.id for i in mask.itemGraph('shadeLoc').forward()]
    lx.eval('select.item {%s} set' % mask.id)
    try:
        lx.eval('mask.setMesh {%s}' % target.name)
    except Exception as exc:
        report['steps'].append(['setMesh ' + target.name, 'failed: %s' % exc])
    if target.id in linked():
        return 'mask.setMesh'
    mask.itemGraph('shadeLoc') >> target.itemGraph('shadeLoc')
    return 'graph' if target.id in linked() else 'not linked'


def type_name(item):
    return lx.service.Scene().ItemTypeName(item.internalItem.Type())


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', 1320), ('resY', 200), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    camera = scene.renderCamera
    modo.LocatorSuperType(camera).position.set((0, 0, 16))
    modo.LocatorSuperType(camera).rotation.set((0, 0, 0))
    camera.channel('focalLen').set(0.05)
    start = -SPACING * (len(CUBES) - 1) / 2
    meshes = {name: cube(name, start + SPACING * index) for index, (name, _) in enumerate(CUBES)}
    lx.eval('select.typeFrom item')
    holders = {}
    holders['Locator'] = scene.addItem('locator', name='Holder Locator')
    meshes['Locator'].setParent(holders['Locator'])
    outer = scene.addItem('locator', name='Outer Locator')
    inner = scene.addItem('locator', name='Inner Locator')
    inner.setParent(outer)
    meshes['Nested'].setParent(inner)
    holders['Nested'] = outer
    holders['Group Locator'] = scene.addItem('groupLocator', name='Holder Group Locator')
    meshes['Group Locator'].setParent(holders['Group Locator'])
    holders['Group'] = scene.addGroup('Holder Group')
    holders['Group'].addItems([meshes['Group']])
    for name, label in (('Sub-group', 'Off'), ('Sub-group applied', 'On')):
        outer_group = scene.addGroup('Outer Group ' + label)
        inner_group = scene.addGroup('Inner Group ' + label)
        inner_group.setParent(outer_group)
        inner_group.addItems([meshes[name]])
        holders[name] = outer_group
    held_locator = scene.addItem('groupLocator', name='Grouped Group Locator')
    meshes['Group of a locator'].setParent(held_locator)
    holders['Group of a locator'] = scene.addGroup('Group Of Locator')
    holders['Group of a locator'].addItems([held_locator])
    plain_locator = scene.addItem('locator', name='Grouped Locator')
    meshes['Group of a plain locator'].setParent(plain_locator)
    holders['Group of a plain locator'] = scene.addGroup('Group Of Plain Locator')
    holders['Group of a plain locator'].addItems([plain_locator])
    holders['Mesh'] = meshes['Mesh']
    group = holders['Group']
    report['group'] = {'type': type_name(group), 'python type': group.type,
                       'members (Group.items)': [i.name for i in modo.item.Group(group).items],
                       'children': [i.name for i in group.children()]}
    for graph in ('itemGroups', 'groups'):
        try:
            report['group']['graph ' + graph] = [[i.name for i in group.itemGraph(graph).forward()], [i.name for i in group.itemGraph(graph).reverse()]]
        except Exception as exc:
            report['group']['graph ' + graph] = 'failed: %s' % exc
    report['sub-group parent'] = scene.item('Inner Group Off').parent.name if scene.item('Inner Group Off').parent else None
    for name, colour in CUBES:
        if colour is None:
            continue
        lx.eval('select.item {%s} set' % render.id)
        before = {m.id for m in scene.items('mask', superType=False)}
        if not step(name + ': add Group', 'shader.create mask'):
            continue
        mask = next(m for m in scene.items('mask', superType=False) if m.id not in before)
        mask.name = name + ' mask'
        lx.eval('select.item {%s} set' % mask.id)
        step(name + ': tag type', 'mask.setPTagType Material')
        # Setting the type leaves the tag at (none), which matches nothing; (all) is no tag.
        mask.channel('ptag').set('')
        way = link(mask, holders[name])
        if 'channels' not in report:
            report['channels'] = {c.name: c.get() for c in mask.channels() if not c.name.startswith(('pos', 'rot', 'scl'))}
        if name == 'Sub-group applied':
            for candidate in ('subMask', 'submask', 'subGroup', 'applySub'):
                try:
                    mask.channel(candidate).set(True)
                    report['sub-group channel'] = candidate
                    break
                except Exception:
                    continue
        lx.eval('select.item {%s} set' % mask.id)
        before = {m.id for m in scene.items('advancedMaterial', superType=False)}
        step(name + ': add Material', 'shader.create advancedMaterial')
        material = next((m for m in scene.items('advancedMaterial', superType=False) if m.id not in before), None)
        if material is not None:
            material.name = name + ' material'
            material.channel('diffCol').set(colour)
            material.channel('diffAmt').set(1.0)
        report['masks'][name] = {'linked by': way, 'item': [(i.name, type_name(i)) for i in mask.itemGraph('shadeLoc').forward()],
                                 'material inside': material is not None and material.parent.id == mask.id}
    report['order'] = ['%s (%s)' % (c.name, c.type) for c in render.children()]
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'item_masks.lxo'))
    try:
        lx.eval('!render.animation {%s} openexr' % str(out / 'modo'))
    except Exception as exc:
        report['modo render'] = 'failed: %s' % exc
    report['rendered'] = [p.name for p in out.glob('modo*')]
    from moonray_modo import scene_export
    warnings = []
    scene_export.export({'path': out / 'masks.rdla', 'format': 'rdla', 'outputs': False, 'collect': False, 'frames': False}, warnings)
    report['warnings'] = warnings
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
