"""MoonRay > MoonShine -> Shader Tree (Revert): what Shader Tree -> MoonShine did, undone in the scene as it is now, so that
it is Modo's materials and texture layers again (the user, 2026-11-28: "reverting to shadertree should have it as normal
modo materials and texture layers"), in one undoable step.

- Each layer the conversion moved into a graph is put back where it is in the Shader Tree, on, with its image loaded
  again (from the file its node names now: a file changed in the graph is the file the layer gets). What the graph's
  Modo Texture node says of the layer is written back onto it: its effect, blend, opacity, invert, constant colour,
  image channel, UV map, projection and tiling; other settings changed in the graph are said in the report.
- A Modo Texture node someone added to the graph with an image is made a new image layer of the material, above it.
- A material the conversion made a graph for (a Modo material) is a Modo material again: its MoonShine override as it
  was before (off), the graph taken off it; any other node in it (one of the user's own that is not a Modo Texture) is
  named in the report, as the Shader Tree has nothing to hold it. A MoonRay material that had a graph of its own keeps
  it, the conversion's nodes taken out of it.
- The MoonShine Material Overrides the conversion made for nested masks are deleted.
- Environments' and lights' layers are put back as they were (shader_tree_environment.put_back, shader_tree_lights).

The graph knows what it was made from: its record (shader_tree_transfer.META_KEY) says whether the material was a Modo
material ('profile': 'modo') or already a MoonRay one ('native'), and since this command's time, the MoonShine settings
it had before ('before'); each node the conversion made says which layer it is and what that layer's image was.
"""
import copy
import os

import lx
import modo

from . import material_override, modo_texture, properties, shader_tree_transfer as transfer
from .host import channel

OVERRIDE_TYPE = 'material.moonrayMoonShine'
LAST_REPORT = []
# What a Modo Texture node's settings are written back as: {setting: (item, channel)}, item 'layer' or 'locator'.
WRITTEN = {'effect': ('layer', 'effect'), 'blend': ('layer', 'blend'), 'opacity': ('layer', 'opacity'), 'invert': ('layer', 'invert'),
           'image_channel': ('layer', 'alpha'), 'uv_map': ('locator', 'uvMap'), 'projection': ('locator', 'projType'),
           'tile_u': ('locator', 'tileU'), 'tile_v': ('locator', 'tileV')}
from .textures import EFFECT_ALIASES
MODO_EFFECTS = {short: name for name, short in EFFECT_ALIASES.items()}


class Report:
    def __init__(self):
        self.materials = []      # materials made Modo materials again
        self.kept_graphs = []    # MoonRay materials that keep their own graph
        self.restored = []       # layers put back
        self.added = []          # (layer name, material name) made from nodes added in the graph
        self.carried = []        # (layer name, settings written back)
        self.not_carried = []    # (layer or node name, what was not written back)
        self.dropped = []        # (material name, node names the Shader Tree cannot hold)
        self.missing = []        # (layer name, why its image is not back)
        self.left = self.missing  # (as shader_tree_environment.put_back reports)
        self.overrides = []      # override items deleted
        self.notes = []

    def lines(self):
        out = ['MoonShine -> Shader Tree: %d material%s back to Modo materials, %d layer%s back in the Shader Tree, %d made from graph nodes.'
               % (len(self.materials), '' if len(self.materials) == 1 else 's', len(self.restored), '' if len(self.restored) == 1 else 's',
                  len(self.added))]
        if not (self.materials or self.restored or self.added or self.kept_graphs or self.overrides):
            out.append('Nothing to revert: no graph in the scene was made by Shader Tree -> MoonShine.')
        if self.kept_graphs:
            out.append('MoonRay materials that keep their own graph (the conversion\'s nodes taken out): %s.' % ', '.join(self.kept_graphs))
        for name, what in self.carried:
            out.append('%s: from the graph, %s.' % (name, what))
        for name, what in self.added:
            out.append('New layer %s on %s, from a node added in the graph.' % (name, what))
        for name, what in self.not_carried:
            out.append('%s: not carried back to the Shader Tree: %s.' % (name, what))
        for name, nodes in self.dropped:
            out.append('%s: graph nodes the Shader Tree cannot hold, left out: %s.' % (name, ', '.join(nodes)))
        for name, why in self.missing:
            out.append('%s: %s.' % (name, why))
        if self.overrides:
            out.append('MoonShine Material Overrides of nested masks deleted: %s.' % ', '.join(self.overrides))
        out.extend(self.notes)
        return out


def _item(scene, identity):
    try:
        return scene.item(identity)
    except (LookupError, RuntimeError, TypeError):
        return None


def _set(item, name, value):
    """A channel of an item set, by its own type (textureLayer's channels for a layer)."""
    if isinstance(value, bool):
        text = 'true' if value else 'false'
    elif isinstance(value, (list, tuple)):
        text = '{%s}' % ' '.join(repr(float(v)) for v in value)
    elif isinstance(value, float):
        text = repr(value)
    else:
        text = '{%s}' % value
    lx.eval('item.channel %s %s item:{%s}' % (name, text, item.id))


def locator_of(layer):
    try:
        return next((i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator'), None)
    except (LookupError, RuntimeError, AttributeError):
        return None


class Clips:
    """Image clips by file: one loaded once for every layer that names it (one already in the scene used again)."""
    def __init__(self, scene):
        self.scene = scene
        self.held = {}
        for clip in scene.items('videoStill'):
            key = self.key(channel(clip, 'filename', ''))
            if key:
                self.held.setdefault(key, clip)

    @staticmethod
    def key(path):
        return os.path.normcase(os.path.abspath(str(path))) if path else ''

    def clip(self, filename, colorspace=None, alpha_mode=None):
        key = self.key(filename)
        if not key:
            return None
        if key in self.held:
            return self.held[key]
        before = {item.id for item in self.scene.items('videoStill')}
        try:
            lx.eval('clip.addStill {%s}' % filename)
        except RuntimeError:
            return None
        made = [item for item in self.scene.items('videoStill') if item.id not in before]
        if not made:
            return None
        clip = made[0]
        try:
            if colorspace and colorspace != '(default)':
                lx.eval('item.channel videoStill$colorspace {%s} item:{%s}' % (colorspace, clip.id))
            if alpha_mode is not None:
                lx.eval('item.channel videoStill$alphaMode %d item:{%s}' % (int(alpha_mode), clip.id))
        except RuntimeError:
            pass
        self.held[key] = clip
        return clip


def image_back(scene, clips, layer, source, file):
    """A layer's image linked again: the file its node names (where it differs from what was recorded, the node's), its
    colour space and alpha as recorded. A UDIM set or image sequence as shader_tree_scene.restore makes them. True where
    the layer has its image."""
    from . import shader_tree_scene as scene_side
    if scene_side.image_of(layer) != (None, None) and not (file and source and file != source.get('filename')):
        return True
    source = dict(source or {})
    if source.get('sequence') or source.get('tiles'):
        return scene_side.restore(scene, layer, source)
    filename = file or source.get('filename')
    clip = clips.clip(filename, source.get('colorspace'), source.get('alpha_mode'))
    if clip is None:
        return False
    lx.eval('select.item {%s} set' % layer.id)
    lx.eval('texture.setIMap {%s}' % clip.name)
    return True


def write_back(layer, node, report):
    """What a Modo Texture node says of its layer, written onto the layer (WRITTEN); the settings it cannot write, said."""
    params = node.get('parameters') or {}
    written, skipped = [], []
    locator = locator_of(layer)
    for key, (where, name) in WRITTEN.items():
        if key not in params:
            continue
        target = layer if where == 'layer' else locator
        if target is None:
            continue
        value = params[key]
        held = channel(target, name, None)
        if key == 'effect':
            # The node holds the kit's short names (textures.EFFECT_ALIASES: diffCol), the layer Modo's (diffColor): the
            # same effect is left as it is, another written in Modo's name.
            if held is not None and EFFECT_ALIASES.get(held, held) == value:
                continue
            value = MODO_EFFECTS.get(value, value)
        if held is not None and (held == value or (isinstance(held, (int, float)) and isinstance(value, (int, float)) and abs(held - value) < 1e-6)):
            continue
        try:
            _set(target, ('textureLayer$%s' if where == 'layer' else 'txtrLocator$%s') % name, value)
            written.append(key)
        except RuntimeError:
            skipped.append(key)
    if params.get('kind') == 'constant' and 'value' in params:
        try:
            _set(layer, 'constant$color', params['value'])
        except RuntimeError:
            skipped.append('value')
    if written:
        report.carried.append((layer.name, ', '.join(written)))
    if skipped:
        report.not_carried.append((layer.name, ', '.join(skipped)))


def new_layer(scene, clips, material, node, report):
    """A Modo Texture node added in the graph with an image: a new image layer above the material, with its settings."""
    params = node.get('parameters') or {}
    file = params.get('file')
    if params.get('kind', 'imageMap') != 'imageMap' or not file:
        return False
    group = material.parent
    if group is None or group.type != 'mask':
        # A material at the top of the Shader Tree (the Base Material): a layer there would shade every material.
        report.not_carried.append((node.get('label') or 'Modo Texture %s' % os.path.basename(file),
                                   'added in the graph of %s, which has no group of its own to hold a new layer' % material.name))
        return False
    clip = clips.clip(file, params.get('color_space') or None)
    if clip is None:
        report.missing.append((node.get('label') or 'Modo Texture', 'its image %s could not be loaded' % file))
        return False
    # Added as an item at the top of the material's group (above the material), its clip linked (Modo gives it a Texture
    # Locator then). shader.create imageMap crashed Modo, the material or its group selected (modo_cl 0xC0000005,
    # tools/probe_cl_new_image_layer.py, 2026-11-28).
    layer = scene.addItem('imageMap', name=os.path.splitext(os.path.basename(file))[0])
    layer.setParent(group, len(group.children()))
    lx.eval('select.item {%s} set' % layer.id)
    lx.eval('texture.setIMap {%s}' % clip.name)
    write_back(layer, node, Report())
    report.added.append((layer.name, material.name))
    return True


def foreign(graph):
    """The graph's nodes the conversion did not make, but its output."""
    root = graph.get('root')
    return {identity: node for identity, node in (graph.get('nodes') or {}).items()
            if identity != root and not transfer.ours(identity, node)}


def without_ours(graph):
    """The graph with the conversion's nodes, its output's inputs wired to them and its record taken out."""
    graph = copy.deepcopy(graph)
    members = graph['nodes']
    mine = {identity for identity, node in members.items() if transfer.ours(identity, node)}
    owned = set((graph.get(transfer.META_KEY) or {}).get('inputs') or ())
    for identity in mine:
        del members[identity]
    for node in members.values():
        inputs = node.get('inputs') or {}
        for key in [k for k, source in inputs.items() if source in mine]:
            del inputs[key]
    root = members.get(graph.get('root'), {})
    for key in [k for k in (root.get('inputs') or {}) if k in owned]:
        del root['inputs'][key]
    if graph.get('displacement') in mine:
        graph.pop('displacement', None)
    graph.pop(transfer.META_KEY, None)
    return graph


def revert_material(scene, clips, material, settings, graph, report):
    meta = graph.get(transfer.META_KEY) or {}
    records = {}
    for identity, node in graph['nodes'].items():
        if transfer.ours(identity, node) and node[transfer.NODE_KEY].get('layer'):
            records.setdefault(node[transfer.NODE_KEY]['layer'], (identity, node))
    if meta.get('material') and meta['material'] != material.id and material.type != OVERRIDE_TYPE:
        # A converted material duplicated after the conversion: the layers its nodes name are the first one's (put back
        # when that one is reverted), so this one's nodes are made layers of its own, as nodes added in the graph are.
        # (Its texture nodes unmarked, as if added; the conversion's other nodes, its blends and helpers, simply go.)
        nodes_now = {}
        for identity, node in graph['nodes'].items():
            if not transfer.ours(identity, node):
                nodes_now[identity] = node
            elif node.get('type') == modo_texture.KIND:
                nodes_now[identity] = {key: value for key, value in node.items() if key != transfer.NODE_KEY}
        graph = dict(graph, nodes=nodes_now)
        records = {}
    for layer_id, (identity, node) in records.items():
        layer = _item(scene, layer_id)
        if layer is None:
            report.missing.append((node[transfer.NODE_KEY].get('name') or layer_id, 'its layer is no longer in the scene'))
            continue
        record = node[transfer.NODE_KEY]
        if layer.type == 'imageMap':
            file = (node.get('parameters') or {}).get('file') if node.get('type') == modo_texture.KIND else None
            if not image_back(scene, clips, layer, record.get('source'), file):
                report.missing.append((layer.name, 'its image %s could not be loaded again; load it by hand'
                                       % ((record.get('source') or {}).get('filename') or file or 'set')))
        if node.get('type') == modo_texture.KIND:
            write_back(layer, node, report)
        if not channel(layer, 'enable', 1):
            lx.eval('item.channel textureLayer$enable true item:{%s}' % layer.id)
        report.restored.append(layer.name)
    others = foreign(graph)
    if meta.get('profile', 'modo') == 'modo':
        added = [node for node in others.values() if node.get('type') == modo_texture.KIND]
        for node in added:
            new_layer(scene, clips, material, node, report)
        left = [node.get('label') or identity for identity, node in others.items() if node.get('type') != modo_texture.KIND]
        if left:
            report.dropped.append((material.name, left))
        before = meta.get('before') or {'moonshine_override': False}
        settings = dict(settings)
        settings.pop('node_graph', None)
        for key in ('moonshine_override', 'native_shader', 'native_parameters'):
            if before.get(key) is None:
                settings.pop(key, None)
            else:
                settings[key] = copy.deepcopy(before[key])
        settings['moonshine_override'] = bool(before.get('moonshine_override', False))
        properties.write(material, settings)
        report.materials.append(material.name)
    else:
        kept = without_ours(graph)
        properties.write(material, material_override.synchronize(settings, kept))
        report.kept_graphs.append(material.name)


def run():
    """Revert the scene (see the module's description); the Report."""
    scene = modo.Scene()
    report = Report()
    clips = Clips(scene)
    overrides = []
    for item in list(scene.items(OVERRIDE_TYPE)) + list(scene.items('advancedMaterial')):
        try:
            settings = properties.read(item)
        except Exception:
            continue
        graph = settings.get('node_graph')
        if not isinstance(graph, dict) or not graph.get('nodes'):
            continue
        meta = graph.get(transfer.META_KEY)
        if meta is None and not any(transfer.ours(i, n) for i, n in graph['nodes'].items()):
            continue
        if item.type == OVERRIDE_TYPE and (meta or {}).get('override_of'):
            revert_material(scene, clips, item, settings, dict(graph, **{transfer.META_KEY: dict(meta, profile='native')}), Report())
            overrides.append(item)
            continue
        revert_material(scene, clips, item, settings, graph, report)
    for item in overrides:
        report.overrides.append(item.name)
        lx.eval('!item.delete item:{%s}' % item.id)
    # Environments.
    from . import shader_tree_environment as environments
    for environment in scene.items('environment', superType=False):
        settings = properties.read(environment)
        graph = settings.get(environments.KEY) if isinstance(settings.get(environments.KEY), dict) else None
        if not graph:
            continue
        held = environments.recorded(graph)
        if not held:
            continue
        environments.put_back(scene, environment, held, report)
        if environments.foreign(graph):
            settings[environments.KEY] = without_ours(graph)
            report.notes.append('Environment %s keeps the nodes of its own in its graph.' % environment.name)
        else:
            settings.pop(environments.KEY, None)
        properties.write(environment, settings)
    # Lights.
    try:
        from . import shader_tree_lights
        lights = shader_tree_lights.restore(scene)
        report.restored.extend(lights.restored)
    except Exception as exc:
        report.notes.append('Lights: their image layers were not put back (%s).' % exc)
    return report
