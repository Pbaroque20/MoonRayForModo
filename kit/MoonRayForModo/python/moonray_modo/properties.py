"""Scene-owned settings; writes are invoked inside undoable Modo commands."""
import base64
import json
import modo
from . import options

TAG = 'MRAY'
# A native MoonRay material added from the Shader Tree's Add Layer list is an item of a type
# named for its shader; one assigned to a mesh is an advancedMaterial that records its shader.
LAYER_PREFIX = 'material.dw.'
# The Add Layer entries that stand for those materials in the Shader Tree's list, and become them when chosen.
ENTRY_PREFIX = 'material.moonrayAdd'
# A material brought in from a MaterialX file: a type of its own in the Shader Tree, to tell it from the rest.
MATERIALX_TYPE = 'material.mtlx'
MATERIAL_TYPES = ('advancedMaterial', 'material.moonrayMoonShine', 'material.moonrayMaterialX')


def is_material(item):
    """Whether an item is a material the plugin renders: Modo's own, or one of the kinds the plugin adds to the Shader Tree."""
    kind = item.type
    return kind in MATERIAL_TYPES or kind.startswith(LAYER_PREFIX) or kind == MATERIALX_TYPE


# Settings being tried out in an editor that is still open, by the material's identity: {identity: {setting:
# value}}. They are read as the material's own, so that the preview shows them, and are written nowhere: the
# editor keeps them with write() when it is accepted, and drops them when it is not.
LIVE = {}


def try_out(items, parameters):
    """Have these materials read with these settings until given_up(), and tell the preview windows to look."""
    for item in items:
        LIVE[item.id] = dict(parameters)
    looked_at(items)


def given_up(items):
    """The materials are read as they are stored again."""
    for item in items:
        LIVE.pop(item.id, None)
    looked_at(items)


def looked_at(items):
    """Tell the preview windows that these materials are to be read again, as an edit in Modo would."""
    try:
        from PySide2 import QtWidgets
        from .panel import Panel
        for widget in QtWidgets.QApplication.allWidgets():
            if isinstance(widget, Panel) and not widget.disposed:
                widget.changes.items.update(item.id for item in items)
    except Exception:
        pass


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
    try:
        tried = LIVE.get(item.id) if LIVE else None
    except (LookupError, RuntimeError, AttributeError):
        tried = None
    if tried:
        data['native_parameters'] = dict(data.get('native_parameters') or {}, **tried)
        graph = data.get('node_graph')
        if graph and graph.get('root') in graph.get('nodes', {}):
            # The graph editor's output node is the same material.
            node = graph['nodes'][graph['root']]
            node['parameters'] = dict(node.get('parameters') or {}, **tried)
    if data.get('diffuse_linked'):
        # Its colour is Modo's diffuse (material_diffuse), though not over a colour being tried out.
        try:
            from .material_diffuse import read_linked
            data = read_linked(item, data)
            if tried:
                data['native_parameters'] = dict(data.get('native_parameters') or {}, **tried)
                graph = data.get('node_graph')
                if graph and graph.get('root') in graph.get('nodes', {}):
                    node = graph['nodes'][graph['root']]
                    node['parameters'] = dict(node.get('parameters') or {}, **tried)
        except (LookupError, RuntimeError, AttributeError):
            pass
    if data.get('native_shader') and not data.get('node_graph'):
        # What the plugin starts such a material with, where it has not been set: a toon material's toon look.
        from .node_defaults import STARTS, started
        if data['native_shader'] in STARTS:
            data['native_parameters'] = started(data['native_shader'], data.get('native_parameters'))
    return data


# A material carries a package named for its native shader. Modo brings a form to the front by
# what its own selection filters report, and those can test for a package.
SHADER_PACKAGE = 'moonray.shader.'


def mark_shader(item, values):
    """Keep the one package that names the material's native shader, and no other. A graph's new output changes it with
    the material selected: Modo lets go of an item whose packages change, and its form with it, so it is selected again."""
    try:
        if item.type != 'advancedMaterial' and not layer_shader(item):
            return
        from . import material_override, shader_library
        shader = material_override.effective(values).get('native_shader') or ''
        if not shader:
            shader = layer_shader(item)
        changes = []
        for name in shader_library.catalog():
            held = bool(item.PackageTest(SHADER_PACKAGE + name))
            if held and name != shader:
                changes.append((item.PackageRemove, name))
            elif not held and name == shader:
                changes.append((item.PackageAdd, name))
        if not changes:
            return
        selected = _is_selected(item)
        for change, name in changes:
            change(SHADER_PACKAGE + name)
        if selected:
            _select_again(item)
    except Exception:
        pass


def is_marked(item):
    """Whether a material holds a package naming any shader."""
    from . import shader_library
    return any(item.PackageTest(SHADER_PACKAGE + name) for name in shader_library.catalog())


def _is_selected(item):
    try:
        import modo
        return any(chosen.id == item.id for chosen in modo.Scene().selected)
    except (AttributeError, LookupError, RuntimeError):
        return False


def _select_again(item):
    import lx
    lx.eval('select.item {%s} add' % item.id)


def write(item, values):
    # Modo's diffuse follows a MoonRay material's main colour, in this same step (material_diffuse).
    try:
        from .material_diffuse import LINKED, on_new_output, to_diffuse
        values = on_new_output(item, values)
        if to_diffuse(item, values):
            values = dict(values, **{LINKED: True})
    except Exception:
        pass
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
