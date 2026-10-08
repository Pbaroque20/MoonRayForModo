"""Scene-owned settings; writes are invoked inside undoable Modo commands."""
import base64
import json
import modo
from . import options

TAG = 'MRAY'
# A native MoonRay material added from the Shader Tree's Add Layer list is an item of a type
# named for its shader; one assigned to a mesh is an advancedMaterial that records its shader.
LAYER_PREFIX = 'material.dw.'
# A material brought in from a MaterialX file: a type of its own in the Shader Tree, to tell it from the rest.
MATERIALX_TYPE = 'material.mtlx'
MATERIAL_TYPES = ('advancedMaterial', 'material.moonrayMoonShine', 'material.moonrayMaterialX')


def is_material(item):
    """Whether an item is a material the plugin renders: Modo's own, or one of the kinds the plugin adds to the Shader Tree."""
    kind = item.type
    return kind in MATERIAL_TYPES or kind.startswith(LAYER_PREFIX) or kind == MATERIALX_TYPE


def layer_shader(item):
    """The shader an Add Layer material is, or '' for any other item."""
    kind = item.type
    return kind[len(LAYER_PREFIX):] if kind.startswith(LAYER_PREFIX) else ''


def read(item):
    try:
        data = json.loads(item.readTag(TAG))
        data = data if isinstance(data, dict) else {}
    except (LookupError, RuntimeError, ValueError, TypeError):
        data = {}
    try:
        shader = layer_shader(item)
    except (LookupError, RuntimeError, AttributeError):
        shader = ''
    try:
        imported = item.type == MATERIALX_TYPE
    except (LookupError, RuntimeError, AttributeError):
        imported = False
    if imported and not data.get('native_shader') and not data.get('node_graph'):
        # Until a file is loaded into it, it is the plain material a MaterialX surface becomes.
        data.update(shader='DwaBaseMaterial', moonshine_override=True, native_shader='DwaBaseMaterial')
        data.setdefault('native_parameters', {})
    if shader and not data.get('native_shader') and not data.get('node_graph'):
        # Its type says what it is, before anything has been written to it.
        data.update(shader='DwaBaseMaterial', moonshine_override=True, native_shader=shader)
        data.setdefault('native_parameters', {})
    return data


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
