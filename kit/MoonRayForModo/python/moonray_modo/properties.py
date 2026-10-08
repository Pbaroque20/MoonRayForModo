"""Scene-owned settings; writes are invoked inside undoable Modo commands."""
import base64
import json
import modo
from . import options

TAG = 'MRAY'


def read(item):
    try:
        data = json.loads(item.readTag(TAG))
        return data if isinstance(data, dict) else {}
    except (LookupError, RuntimeError, ValueError, TypeError):
        return {}


# A material carries a package named for its native shader. Modo brings a form to the front by
# what its own selection filters report, and those can test for a package.
SHADER_PACKAGE = 'moonray.shader.'


def mark_shader(item, values):
    """Keep the one package that names the material's native shader, and no other."""
    try:
        if item.type != 'advancedMaterial':
            return
        from . import material_override, shader_library
        shader = material_override.effective(values).get('native_shader') or ''
        for name in shader_library.catalog():
            held = bool(item.PackageTest(SHADER_PACKAGE + name))
            if held and name != shader:
                item.PackageRemove(SHADER_PACKAGE + name)
            elif not held and name == shader:
                item.PackageAdd(SHADER_PACKAGE + name)
    except Exception:
        pass


def write(item, values):
    item.setTag(TAG, json.dumps(values, sort_keys=True, separators=(',', ':')))
    mark_shader(item, values)
    from .property_notifications import notify
    notify()


def selected_meshes():
    return [item for item in modo.Scene().selected if item.type == 'mesh']


def selected_geometry():
    return [item for item in modo.Scene().selected if item.type in ('mesh','meshInst','replicator')]


def scene_settings():
    return read(modo.Scene().renderItem)


def encode(values):
    return base64.urlsafe_b64encode(json.dumps(values).encode('utf-8')).decode('ascii')


def decode(value):
    result = json.loads(base64.urlsafe_b64decode(value.encode('ascii')).decode('utf-8'))
    if not isinstance(result, dict):
        raise ValueError('Settings must be an object')
    return result
