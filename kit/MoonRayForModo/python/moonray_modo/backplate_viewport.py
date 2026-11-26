"""A Backplate's photo in Modo's viewport: a Modo Backdrop (a reference image) showing its photo as the renders show
it. Modo draws it; it is never rendered (the kit leaves Backdrops out of its scenes).

- Backdrop Distance 0 (the photo behind everything): under the Backplate, Camera projection, filling the frame of any
  view looking through a camera.
- Backdrop Distance above 0: a card standing that far in front of the render camera, facing it and filling its view's
  width, as the renders' backdrop plane (backplate.card) stands; under the camera, so that it moves with it, and seen in
  perspective views too. Modo draws reference images behind meshes, so a mesh past the card still shows in front of it.

Kept as the Backplate's "backplate in the viewport", its photo and its Backdrop Distance say, and as the render camera's
lens and film: made, changed or taken away by the command moonray.backplate.viewport, run when a scene opens, when a
Backplate is added or deleted and when those settings change (lxserv/moonray_entities.py).

The HDRI likewise ("HDRI in the viewport"): a Modo environment of the kit's own at the top of the Shader Tree, an image
layer of the HDRI on a spherical Texture Locator turned by HDRI Rotation about Y, as the renders turn it (backplate
.hdri_matrix), so that Modo's viewport shows the HDRI behind the scene where it shows the environment, and follows its
rotation. It is never rendered by the kit (environments.collect leaves out the environments that carry OWNER: the
Backplate's HDRI is its own entry there)."""
import json
from pathlib import Path

from . import entities

CLASS = 'BackplateEnvironment'
# The tags a Backdrop (or environment) of the kit's carries: the Backplate it shows the photo (or HDRI) of, and how it
# was set up (want(), want_hdri()).
OWNER = 'MRBP'
SHOWN = 'MRBF'
# The Backplate settings and the camera channels its Backdrop and environment follow (the listeners in
# lxserv/moonray_entities.py).
PLATE_KEYS = ('plate', 'viewport_plate', 'backdrop_distance', 'hdri', 'hdri_rotation', 'viewport_hdri')
CAMERA_CHANNELS = ('focalLen', 'apertureX', 'projType')
_WIDTHS = {}


def _channel(item, key, default=None):
    try:
        return item.channel(entities.CHANNEL_PREFIX + key).get()
    except (AttributeError, LookupError, RuntimeError, TypeError, ValueError):
        return default


def _own(item, name, default=None):
    try:
        return item.channel(name).get()
    except (AttributeError, LookupError, RuntimeError, TypeError, ValueError):
        return default


def _tag(item, key):
    try:
        return item.readTag(key) if item.hasTag(key) else ''
    except (AttributeError, LookupError, RuntimeError, TypeError):
        return ''


def _same(a, b):
    return a.replace('\\', '/').lower() == b.replace('\\', '/').lower()


def image_width(path):
    """The photo's width in pixels (Qt reads the common kinds; the kit's image tool the rest), or None."""
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    key = (str(path).lower(), stat.st_size, stat.st_mtime_ns)
    if key not in _WIDTHS:
        width = None
        try:
            from PySide2 import QtGui
            size = QtGui.QImageReader(str(path)).size()
            width = size.width() if size.isValid() and size.width() > 0 else None
        except Exception:
            width = None
        if width is None:
            try:
                import re
                import subprocess
                from . import native
                tool = native.tool('oiiotool.exe')
                text = subprocess.run([str(tool), '--info', str(path)], env=native.environment(tool.parent), capture_output=True,
                                      text=True, timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
                found = re.search(r':\s*(\d+)\s*x\s*(\d+)', text)
                width = int(found.group(1)) if found else None
            except Exception:
                width = None
        _WIDTHS[key] = width
    return _WIDTHS[key]


def want(plate, camera, width=image_width):
    """How a Backplate's Backdrop is to be set up, as text (its SHOWN tag), or '' where it shows none (switched off, or no
    photo). camera: the render camera, for a card (Backdrop Distance above 0)."""
    if not _channel(plate, 'viewport_plate', True):
        return ''
    photo = str(_channel(plate, 'plate', '') or '').strip()
    if not photo:
        return ''
    setup = {'photo': photo.replace('\\', '/').lower(), 'path': photo}
    distance = float(_channel(plate, 'backdrop_distance', 0.0) or 0.0)
    pixels = width(photo) if distance > 0 and camera is not None else None
    if distance > 0 and camera is not None and pixels:
        film = max(float(_own(camera, 'apertureX', 0.036) or 0.036), 1e-6)
        focal = max(float(_own(camera, 'focalLen', 0.05) or 0.05), 1e-6)
        # Across the camera's view at that distance (an orthographic camera: its width), over the photo's pixels.
        across = film if _own(camera, 'projType', 'persp') == 'ortho' else distance * film / focal
        setup.update(card=True, camera=camera.id, distance=round(distance, 6), pixel=round(across / pixels, 9))
    return json.dumps(setup, sort_keys=True)


def plan(plates, backdrops):
    """What to do so that each Backplate has the Backdrop it wants and no other. plates: {ident: want() or ''};
    backdrops: [(ident, owner, set up as)], the kit's Backdrops. Returns (remove, make, change): Backdrops to take away;
    Backplates needing one made, with its setup; Backdrops to set up again, with it."""
    remove, make, change = [], [], []
    kept = set()
    for ident, owner, shown in backdrops:
        setup = plates.get(owner, '')
        if not setup or owner in kept:
            remove.append(ident)
            continue
        kept.add(owner)
        if shown != setup:
            change.append((ident, setup))
    for owner, setup in plates.items():
        if setup and owner not in kept:
            make.append((owner, setup))
    return remove, make, change


def want_hdri(plate):
    """How a Backplate's viewport environment is to be set up, as text (its SHOWN tag), or '' where it shows none
    ("HDRI in the viewport" off, or no HDRI): the HDRI and its Rotation (degrees about Y)."""
    if not _channel(plate, 'viewport_hdri', True):
        return ''
    hdri = str(_channel(plate, 'hdri', '') or '').strip()
    if not hdri:
        return ''
    try:
        rotation = float(_channel(plate, 'hdri_rotation', 0.0) or 0.0)
    except (TypeError, ValueError):
        rotation = 0.0
    return json.dumps({'hdri': hdri.replace('\\', '/').lower(), 'path': hdri, 'rotation': round(rotation, 6)}, sort_keys=True)


def viewport_only(item):
    """Whether a Modo environment is one of the kit's, showing a Backplate's HDRI in the viewport alone: never read
    into a render (environments.collect)."""
    return bool(_tag(item, OWNER))


def _state(scene):
    kind = entities.item_type(CLASS)
    items = list(scene.items())
    camera = scene.renderCamera
    plates = {item.id: want(item, camera) for item in items if item.type == kind}
    backdrops = [(b.id, _tag(b, OWNER), _tag(b, SHOWN)) for b in items if b.type == 'backdrop' and _tag(b, OWNER)]
    return plates, backdrops


def _sky_state(scene):
    """As _state, for the HDRI: each Backplate's want_hdri, and the kit's viewport environments."""
    kind = entities.item_type(CLASS)
    items = list(scene.items())
    skies = {item.id: want_hdri(item) for item in items if item.type == kind}
    shown = [(e.id, _tag(e, OWNER), _tag(e, SHOWN)) for e in items if e.type == 'environment' and _tag(e, OWNER)]
    return skies, shown


def lacking(scene=None):
    """Whether any Backplate's Backdrop or viewport environment is missing, out of date or left over, so that a scene
    in order is not changed (and its undo list not added to)."""
    import modo
    scene = scene or modo.Scene()
    return any(plan(*_state(scene))) or any(plan(*_sky_state(scene)))


def _clip(scene, photo):
    """The scene's image (Clip) of the photo, loaded where it is not yet."""
    def find():
        for clip in scene.items('videoStill'):
            try:
                if _same(str(clip.channel('filename').get() or ''), photo):
                    return clip
            except (AttributeError, LookupError, RuntimeError, TypeError, ValueError):
                continue
        return None
    clip = find()
    if clip is None:
        import lx
        lx.eval('!clip.addStill {%s}' % photo)
        clip = find()
    return clip


def _set_up(scene, backdrop, owner, text):
    import lx
    setup = json.loads(text)
    clip = _clip(scene, setup['path'])
    if clip is None:
        return False
    card = setup.get('card')
    parent = setup['camera'] if card else owner
    lx.eval('!item.parent {%s} {%s} inPlace:0' % (backdrop.id, parent))
    lx.eval('select.item {%s} set' % backdrop.id)
    lx.eval('!backdrop.edit image:{%s}' % clip.id)
    # A card faces its camera, which looks down its own -Z: front projection, that far ahead. Otherwise the photo fills
    # the frame of a view through a camera (camera projection), where it stands under the Backplate making no matter.
    lx.eval('!item.channel backdrop$projection %s' % ('front' if card else 'camera'))
    if card:
        lx.eval('!item.channel backdrop$pixelSize %s' % setup['pixel'])
    for axis, value in (('X', 0.0), ('Y', 0.0), ('Z', -setup['distance'] if card else 0.0)):
        lx.eval('!transform.channel pos.%s %s' % (axis, value))
    for axis in 'XYZ':
        lx.eval('!transform.channel rot.%s 0.0' % axis)
    try:
        lx.eval('!backdrop.show showPersp:%s' % ('true' if card else 'false'))
    except RuntimeError:
        pass
    try:
        lx.eval('!item.channel backdrop$renderItem false')
    except RuntimeError:
        pass
    backdrop.setTag(SHOWN, text)
    return True


def _sky_layer(scene, environment):
    """The image layer of a viewport environment, made where it has none, and its Texture Locator."""
    import lx
    layer = next((i for i in environment.children() if i.type == 'imageMap'), None)
    if layer is None:
        lx.eval('item.create imageMap')
        layer = scene.selected[-1]
        lx.eval('texture.parent {%s} %d item:{%s}' % (environment.id, len(environment.children()), layer.id))
    locator = next((i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator'), None)
    return layer, locator


def _set_up_sky(scene, environment, owner, text):
    """A viewport environment showing its Backplate's HDRI turned by its Rotation, as the renders show it: an image
    layer on a spherical Texture Locator along Y, turned about Y (degrees, as Modo's Rotation Y and the Backplate's)."""
    import lx
    setup = json.loads(text)
    clip = _clip(scene, setup['path'])
    if clip is None:
        return False
    layer, locator = _sky_layer(scene, environment)
    if locator is None:
        return False
    lx.eval('select.item {%s} set' % layer.id)
    lx.eval('texture.setIMap {%s}' % clip.id)
    lx.eval('!item.channel imageMap$effect envColor')
    lx.eval('select.item {%s} set' % locator.id)
    lx.eval('!item.channel txtrLocator$projType spherical')
    lx.eval('!item.channel txtrLocator$projAxis 1')
    for axis in 'XZ':
        lx.eval('!transform.channel rot.%s 0.0' % axis)
    lx.eval('!transform.channel rot.Y %s' % setup['rotation'])
    environment.setTag(SHOWN, text)
    return True


def _make_sky(scene, owner, setup):
    """A new viewport environment for a Backplate (Modo puts a new environment at the top of the Shader Tree's
    environments)."""
    plate = scene.item(owner)
    environment = scene.addItem('environment')
    environment.setTag(OWNER, owner)
    environment.name = '%s HDRI (viewport)' % plate.name
    if not _set_up_sky(scene, environment, owner, setup):
        _remove_sky(scene, environment.id)


def _remove_sky(scene, ident):
    """A viewport environment taken away with its image layer and that layer's Texture Locator."""
    try:
        environment = scene.item(ident)
    except (LookupError, RuntimeError):
        return
    gone = []
    for layer in environment.children():
        try:
            gone += [i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator']
        except (AttributeError, LookupError, RuntimeError):
            pass
    for item in gone + [environment]:
        try:
            scene.removeItems(item, children=item is environment)
        except (LookupError, RuntimeError, TypeError):
            pass


def sync():
    """Brings every Backplate's Backdrop and viewport environment in line with its settings. Run inside a command
    (moonray.backplate.viewport)."""
    import lx
    import modo
    scene = modo.Scene()
    plates, backdrops = _state(scene)
    remove, make, change = plan(plates, backdrops)
    skies, shown = _sky_state(scene)
    sky_remove, sky_make, sky_change = plan(skies, shown)
    if not (remove or make or change or sky_remove or sky_make or sky_change):
        return
    selected = [item.id for item in scene.selected]
    owners = {ident: owner for ident, owner, _ in backdrops}
    sky_owners = {ident: owner for ident, owner, _ in shown}
    try:
        for ident in remove:
            try:
                scene.removeItems(scene.item(ident))
            except (LookupError, RuntimeError):
                pass
        for ident in sky_remove:
            _remove_sky(scene, ident)
        for ident, setup in change:
            _set_up(scene, scene.item(ident), owners[ident], setup)
        for ident, setup in sky_change:
            _set_up_sky(scene, scene.item(ident), sky_owners[ident], setup)
        for owner, setup in sky_make:
            _make_sky(scene, owner, setup)
        for owner, setup in make:
            plate = scene.item(owner)
            lx.eval('item.create backdrop')
            backdrop = scene.selected[-1]
            backdrop.setTag(OWNER, owner)
            backdrop.name = '%s photo (viewport)' % plate.name
            if not _set_up(scene, backdrop, owner, setup):
                scene.removeItems(backdrop)
    finally:
        # The selection as it was: the user is editing the Backplate, not the Backdrop.
        lx.eval('select.drop item')
        for ident in selected:
            try:
                lx.eval('select.item {%s} add' % ident)
            except RuntimeError:
                pass
