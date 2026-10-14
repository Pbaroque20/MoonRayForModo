"""The colour management last chosen through MoonRay's settings, kept on this machine.

A scene that has not chosen its own view starts with what was last chosen, in this Modo and the next one opened. Only
inside Modo: anywhere else (tests, the command line) nothing is remembered and nothing is read.
"""
# What is remembered: how the picture is viewed. Not the exposure, which belongs to a picture.
KEYS = ('view', 'lut', 'lut_space', 'config', 'source', 'display', 'ocio_view')
_held = None


def _store():
    import lx  # noqa: F401  (only inside Modo)
    from PySide2 import QtCore
    from . import native
    return QtCore.QSettings('MoonRayForModo', native.settings_name())


def remembered():
    """What was last chosen, by key; empty where nothing was, or outside Modo."""
    global _held
    if _held is None:
        try:
            store = _store()
            _held = {key: str(store.value('display/' + key)) for key in KEYS if store.contains('display/' + key)}
        except Exception:
            return {}
    return dict(_held)


def remember(key, value):
    """Keep one of the view's settings as chosen."""
    global _held
    if key not in KEYS:
        return
    try:
        store = _store()
        store.setValue('display/' + key, str(value))
        held = remembered()
        held[key] = str(value)
        _held = held
    except Exception:
        pass
