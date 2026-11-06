# python
"""Command line: the tester's Group Mask set-up rebuilt on the car's own tyre. Opens test-results/rt-car/car_aces.lxo,
keeps one tyre (the first mesh named Reifen*) and deletes the other meshes, and in the tread's material group
(Reifen_Laufflaeche) adds a group on top holding a purple Material, masked by the 'tire dirt mask' image on the UV map
Laufflaeche (a white band with soft edges): purple where the mask is white, the tread's own material where it is
black. A camera is put looking at the tyre's tread. Saved as test-results/tyre-group-mask/tyre_group_mask.lxo and
rendered by Modo (modo.*.exr); report.json has the Shader Tree."""
import json
import math
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tyre-group-mask')
out.mkdir(parents=True, exist_ok=True)
report = {}


def save(step):
    report.setdefault('steps', []).append(step)
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str), encoding='utf-8')


def new_item(kind, before):
    return next(i for i in modo.Scene().iterItems() if i.id not in before and i.type == kind)


def create(kind, under):
    scene = modo.Scene()
    before = {i.id for i in scene.iterItems()}
    lx.eval('select.item {%s} set' % under.id)
    lx.eval('shader.create %s' % kind)
    return new_item(kind, before)


def tree(item, depth=0):
    rows = []
    for child in item.children():
        detail = ''
        try:
            detail = ' effect=%s' % child.channel('effect').get()
        except Exception:
            pass
        rows.append('  ' * depth + '%s (%s)%s' % (child.name, child.type, detail))
        rows += tree(child, depth + 1)
    return rows


try:
    lx.eval('scene.open {%s} normal' % r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\rt-car\car_aces.lxo')
    scene = modo.Scene()
    meshes = list(scene.items('mesh'))
    report['reifen'] = [m.name for m in meshes if m.name.lower().startswith('reifen')]
    tyre = next(m for m in meshes if m.name.lower().startswith('reifen'))
    report['tyre'] = tyre.name
    save('picked')
    for mesh in meshes:
        if mesh.id != tyre.id:
            try:
                scene.removeItems(mesh)
            except Exception as exc:
                report.setdefault('remove_errors', []).append('%s: %s' % (mesh.name, exc))
    save('removed')
    # Where the tyre stands: its points through its world matrix.
    from moonray_modo import mesh_reader
    from moonray_modo.host import world_matrix
    from moonray_modo.coordinates import transform
    geometry = modo.meshgeometry.MeshProvider.meshFromMeshChannel(tyre._item, 'deformed')
    whole = mesh_reader.read(geometry)
    matrix = world_matrix(tyre)
    placed = [transform(list(p), matrix) for p in list(whole.vertices)[::50]]
    low = [min(p[k] for p in placed) for k in range(3)]
    high = [max(p[k] for p in placed) for k in range(3)]
    middle = [(a + b) / 2 for a, b in zip(low, high)]
    size = max(b - a for a, b in zip(low, high))
    report['bounds'] = [low, high]
    # The camera beside the car, a little in front and above, looking at the tyre: its tread and outer wall.
    camera = scene.renderCamera
    side = -1.0 if middle[0] < 0 else 1.0
    eye = (middle[0] + side * size * 1.6, middle[1] + size * 0.5, middle[2] + size * 1.6)
    camera.position.set(eye)
    dx, dy, dz = middle[0] - eye[0], middle[1] - eye[1], middle[2] - eye[2]
    yaw = math.atan2(-dx, -dz)
    pitch = math.atan2(dy, math.hypot(dx, dz))
    camera.rotation.set((pitch, yaw, 0.0))
    render = scene.renderItem
    # One frame only: the car's scene has a frame range of its own.
    for name, value in (('resX', 640), ('resY', 480), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    save('camera')
    tread = next(m for m in scene.items('mask', superType=False) if m.channel('ptag').get() == 'Reifen_Laufflaeche')
    # The group on top of the tread's material group, holding a purple Material, masked by the dirt mask image.
    before = {i.id for i in scene.iterItems()}
    lx.eval('select.item {%s} set' % tread.id)
    lx.eval('shader.create mask')
    group = new_item('mask', before)
    group.name = 'Purple Group'
    save('group')
    purple = create('advancedMaterial', group)
    purple.name = 'Purple'
    save('purple')
    for axis, value in zip('RGB', (0.6, 0.0, 0.9)):
        purple.channel('diffCol.' + axis).set(value)
    # As the tester did: the tread's own 'tire dirt mask' layer moved into the group, made its Group Mask at Normal, 100%.
    image = next(i for i in scene.iterItems() if i.type == 'imageMap' and i.name.startswith('tire dirt mask'))
    lx.eval('select.item {%s} set' % image.id)
    lx.eval('texture.parent {%s} -1' % group.id)
    save('moved')
    image.channel('effect').set('groupMask')
    image.channel('blend').set('normal')
    image.channel('opacity').set(1.0)
    save('imap')
    report['shader_tree'] = tree(tread)
    save('built')
    report['image_parent'] = image.parent.name if image.parent is not None else None
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'tyre_group_mask.lxo'))
    save('saved')
    lx.eval('!render.animation {%s} openexr' % str(out / 'modo'))
    report['rendered'] = [p.name for p in out.glob('modo*')]
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str), encoding='utf-8')
