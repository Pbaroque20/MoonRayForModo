"""A Backplate's photo in Modo's viewport: a Modo Backdrop (a reference image) showing its photo as the renders show
it. Modo draws it; it is never rendered (the kit leaves Backdrops out of its scenes).

- Backdrop Distance 0 (the photo behind everything): under the Backplate, Camera projection, filling the frame of any
  view looking through a camera.
- Backdrop Distance above 0: a card standing that far in front of the render camera, facing it and filling its view's
  width, as the renders' backdrop plane (backplate.card) stands; under the camera, so that it moves with it, and seen in
  perspective views too. Modo draws reference images behind meshes, so a mesh past the card still shows in front of it.

Kept as the Backplate's "backplate in the viewport", its photo and its Backdrop Distance say, and as the render camera's
lens and film: made, changed or taken away by the command moonray.backplate.viewport, run when a scene opens, when a
Backplate is added or deleted and when those settings change (lxserv/moonray_entities.py)."""
import json
from pathlib import Path

from . import entities

CLASS = 'BackplateEnvironment'
# The tags a Backdrop of the kit's carries: the Backplate it shows the photo of, and how it was set up (want()).
OWNER = 'MRBP'
SHOWN = 'MRBF'
# The Backplate settings and the camera channels its Backdrop follows (the listeners in lxserv/moonray_entities.py).
PLATE_KEYS = ('plate', 'viewport_plate', 'backdrop_distance')
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


def _state(scene):
    kind = entities.item_type(CLASS)
    items = list(scene.items())
    camera = scene.renderCamera
    plates = {item.id: want(item, camera) for item in items if item.type == kind}
    backdrops = [(b.id, _tag(b, OWNER), _tag(b, SHOWN)) for b in items if b.type == 'backdrop' and _tag(b, OWNER)]
    return plates, backdrops


def lacking(scene=None):
    """Whether any Backplate's Backdrop is missing, out of date or left over, so that a scene in order is not changed
    (and its undo list not added to)."""
    import modo
    scene = scene or modo.Scene()
    return any(plan(*_state(scene)))


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


def sync():
    """Brings every Backplate's Backdrop in line with its settings. Run inside a command (moonray.backplate.viewport)."""
    import lx
    import modo
    scene = modo.Scene()
    plates, backdrops = _state(scene)
    remove, make, change = plan(plates, backdrops)
    if not (remove or make or change):
        return
    selected = [item.id for item in scene.selected]
    owners = {ident: owner for ident, owner, _ in backdrops}
    try:
        for ident in remove:
            try:
                scene.removeItems(scene.item(ident))
            except (LookupError, RuntimeError):
                pass
        for ident, setup in change:
            _set_up(scene, scene.item(ident), owners[ident], setup)
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
