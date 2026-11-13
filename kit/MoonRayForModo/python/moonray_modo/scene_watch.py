"""Scenes closing, told to whoever holds an item of one (the graph editor, docked or not). An item of a closed scene
still answers as if it were there (its id, its name; ids are the same from one scene to the next), and a value written
to it crashed Modo; so the editor lets go of its material when its scene is destroyed.

LISTENERS are called with the key of the scene destroyed (key()), or None where it could not be told."""
import lx
import lxifc

LISTENERS = []
_held = {}


def key(scene):
    """What tells one scene from another while both are open: the address of its scene object."""
    try:
        return lx.object.Scene(scene).__peekobj__()
    except Exception:
        return None


def key_of_item(item):
    """The key of the scene an item is in; None where it cannot be told."""
    try:
        return key(lx.object.Item(item).Context())
    except Exception:
        return None


class _Listener(lxifc.SceneItemListener):
    def sil_SceneDestroy(self, scene):
        told = key(scene)
        for listener in list(LISTENERS):
            try:
                listener(told)
            except Exception:
                pass


def watch(listener):
    """Call listener(key) each time a scene is destroyed, until unwatch(listener)."""
    if 'com' not in _held:
        # One COM object kept for the listener, as Modo's SDK asks (changes.Changes).
        held = _Listener()
        com = lx.object.Unknown(held)
        try:
            lx.service.Listener().AddListener(com)
            _held.update(listener=held, com=com)
        except (RuntimeError, LookupError):
            return
    if listener not in LISTENERS:
        LISTENERS.append(listener)


def unwatch(listener):
    if listener in LISTENERS:
        LISTENERS.remove(listener)
