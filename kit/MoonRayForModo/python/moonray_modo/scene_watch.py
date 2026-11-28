"""Scenes closing, told to whoever holds an item of one (the graph editor, docked or not). An item of a closed scene
still answers as if it were there (its id, its name; ids are the same from one scene to the next), and a value written
to it crashed Modo; so the editor lets go of its material when its scene is destroyed.

LISTENERS are called with the key of the scene destroyed (key()), or None where it could not be told.

ITEM_LISTENERS are called with (ident, scene key) of each item about to be deleted: a graph editor open on a material
that was deleted went on reading and writing it (its preview, its timers) and Modo crashed, where the editor should
close (watch_items)."""
import lx
import lxifc

LISTENERS = []
ITEM_LISTENERS = []
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

    def sil_ItemRemove(self, item):
        # Told before the item goes, while it still answers: who holds it lets go now, not after.
        if not ITEM_LISTENERS:
            return
        try:
            held = lx.object.Item(item)
            ident = held.Ident()
            told = key(held.Context())
        except Exception:
            return
        for listener in list(ITEM_LISTENERS):
            try:
                listener(ident, told)
            except Exception:
                pass


def _hold():
    """The one listener Modo is given, added at the first watch; False where it could not be."""
    if 'com' not in _held:
        # One COM object kept for the listener, as Modo's SDK asks (changes.Changes).
        held = _Listener()
        try:
            # Taken out as Modo quits, while Python still stands (quit_release).
            from . import quit_release
            com = quit_release.listen(held)
            _held.update(listener=held, com=com)
        except (RuntimeError, LookupError):
            return False
    return True


def watch(listener):
    """Call listener(key) each time a scene is destroyed, until unwatch(listener)."""
    if _hold() and listener not in LISTENERS:
        LISTENERS.append(listener)


def unwatch(listener):
    if listener in LISTENERS:
        LISTENERS.remove(listener)


def watch_items(listener):
    """Call listener(ident, key) for each item about to be deleted, until unwatch_items(listener)."""
    if _hold() and listener not in ITEM_LISTENERS:
        ITEM_LISTENERS.append(listener)


def unwatch_items(listener):
    if listener in ITEM_LISTENERS:
        ITEM_LISTENERS.remove(listener)
