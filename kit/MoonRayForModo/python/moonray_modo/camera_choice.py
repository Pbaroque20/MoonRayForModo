"""Which camera the scene is rendered through: Modo's render camera, or one of MoonRay's own.

A MoonRay camera item renders in place of the Modo camera while its "render through this
camera" channel is on. This module is the one place that reads and sets those channels, so
that at most one is ever on; the preview window and the Render item's form both choose
through it.
"""
import modo
from . import entities

CHANNEL = entities.CHANNEL_PREFIX + 'modo_render_camera'


def cameras(scene=None):
    """The scene's MoonRay camera items, in name order."""
    scene = scene or modo.Scene()
    found = []
    for name in entities.classes('camera'):
        try:
            found += list(scene.items(entities.item_type(name), superType=False))
        except (LookupError, RuntimeError, TypeError):
            pass
    return sorted(found, key=lambda item: item.name.casefold())


def label(item):
    return '%s: %s' % (entities.display(item.type[len(entities.TYPE_PREFIX):]), item.name)


def choices(scene=None):
    """(label, item id) for every camera that can be rendered through; the Modo camera's id is ''."""
    scene = scene or modo.Scene()
    try:
        name = scene.renderCamera.name
    except Exception:
        name = 'none'
    return [('Modo camera: ' + name, '')] + [(label(item), item.id) for item in cameras(scene)]


def rendering(item):
    try:
        return bool(item.channel(CHANNEL).get())
    except Exception:
        return False


def current(scene=None):
    """The id of the MoonRay camera being rendered through, or '' for the Modo camera."""
    return next((item.id for item in cameras(scene) if rendering(item)), '')


def choose(identity, scene=None):
    """Render through the camera with this id, or the Modo camera for ''. Call inside a command."""
    for item in cameras(scene):
        wanted = item.id == identity
        if rendering(item) != wanted:
            item.channel(CHANNEL).set(wanted)
