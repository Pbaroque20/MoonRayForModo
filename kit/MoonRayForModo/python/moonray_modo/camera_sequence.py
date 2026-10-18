"""Sequential cameras: keys that each make a camera the one rendered through over a range of frames.

The keys are kept with the scene, in its MoonRay settings, as {'enabled': bool, 'keys': [{'camera', 'first', 'last'}]},
a camera by its item's identity: one of Modo's cameras, or one of MoonRay's camera items. The scene is read through
the camera keyed at the frame it is read at (host.snapshot), so the preview, Render to a File, Render Animation and a
playblast all follow the keys. A frame no key covers is rendered through the render camera, as without keys; where
keys overlap, the one that starts later is the one in force."""

DEFAULT = {'enabled': True, 'keys': []}


def normalized(sequence):
    """The keys as kept: whole frames, each key's first no later than its last, in the order they start. Raises
    ValueError for keys that cannot be read."""
    sequence = sequence if isinstance(sequence, dict) else {}
    keys = []
    for key in sequence.get('keys') or []:
        if not isinstance(key, dict) or not str(key.get('camera') or ''):
            raise ValueError('A camera key names no camera')
        first, last = int(key.get('first', 0)), int(key.get('last', 0))
        if last < first:
            first, last = last, first
        keys.append({'camera': str(key['camera']), 'first': first, 'last': last})
    keys.sort(key=lambda key: (key['first'], key['last']))
    return {'enabled': bool(sequence.get('enabled', True)), 'keys': keys}


def camera_at(sequence, frame):
    """The camera keyed at a frame, by its identity, or None where no key covers it or the keys are off."""
    sequence = normalized(sequence)
    if not sequence['enabled']:
        return None
    found = None
    for key in sequence['keys']:
        if key['first'] <= frame <= key['last']:
            found = key['camera']
    return found


def overlaps(sequence):
    """The keys that cover some of the same frames, as pairs of their places in the list."""
    keys = normalized(sequence)['keys']
    return [(a, b) for a in range(len(keys)) for b in range(a + 1, len(keys))
            if keys[a]['first'] <= keys[b]['last'] and keys[b]['first'] <= keys[a]['last']]


def gaps(sequence, first, last):
    """The frames between first and last no key covers, as (first, last) ranges."""
    keys = normalized(sequence)['keys']
    found, start = [], None
    for frame in range(first, last + 1):
        covered = any(key['first'] <= frame <= key['last'] for key in keys)
        if not covered and start is None:
            start = frame
        elif covered and start is not None:
            found.append((start, frame - 1)); start = None
    if start is not None:
        found.append((start, last))
    return found


def keyed(scene, frame):
    """The camera item keyed at a frame in a Modo scene, or None: (the item, whether it is one of MoonRay's camera items).
    A key whose camera is gone is passed over."""
    from . import properties
    sequence = properties.scene_settings().get('camera_sequence') or {}
    try:
        identity = camera_at(sequence, frame)
    except ValueError:
        return None
    if identity is None:
        return None
    try:
        item = scene.item(identity)
    except LookupError:
        return None
    from . import entities
    return item, entities.class_of(item) is not None
