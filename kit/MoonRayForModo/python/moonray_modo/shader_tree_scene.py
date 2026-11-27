"""MoonRay > Move Shader Tree Textures to MoonShine Graphs: the images that Shader Tree layers lay on Modo's materials
moved into the materials' MoonShine graphs, as Image nodes that name the files, which MoonRay converts and loads when it
renders; the layers switched off (kept, to be switched on again) and their image clips taken out of the scene, so that
Modo holds the images no more. Run again, it brings each graph up to date with its layers: a new layer's image added, a
layer whose mask, tag or effect changed wired anew, the nodes of a layer that is gone taken out. All in the one undoable
step of the command that calls run().

The layers are read as the kit reads them for a render (layers.collect); what each becomes is shader_tree_transfer's.
Which layers belong to which material is read from the Shader Tree's shape: a layer above a material in the material's
own group (or in a group of layers there) shades the surfaces the material does, whatever the group is for (a material
tag, a part, a selection set, items). A layer inside a group of its own for some of those surfaces (a nested mask) is
moved into a MoonShine Material Override made in that group, whose graph is the material's with that group's layers.
"""
import copy
import json
import os

import lx
import modo

from . import host, layers, material_override, nodes, properties, shader_tree_transfer as transfer
from .host import channel
from .mask_types import tag_kind, mask_items

OVERRIDE_TYPE = 'material.moonrayMoonShine'
# The last run's report lines (for probes and the Event Log).
LAST_REPORT = []
NOT_LAYERS = ('defaultShader', 'renderOutput', 'envMaterial', 'furMaterial', 'polyRender', 'environment', 'mask')


class Report:
    def __init__(self):
        self.moved = []          # (layer name, material name)
        self.made = []           # graphs made: material names
        self.updated = []        # graphs brought up to date
        self.overrides = []      # MoonShine Material Overrides made for nested masks
        self.unloaded = []       # image clips taken out
        self.kept = []           # (clip name, why)
        self.left = []           # (layer or material name, why)
        self.restored = []       # layers put back in the Shader Tree
        self.removed_nodes = 0
        self.notes = []

    def lines(self):
        out = ['Move Shader Tree Textures to MoonShine Graphs: %d layer%s moved, %d graph%s made, %d updated, %d image clip%s unloaded.'
               % (len(self.moved), '' if len(self.moved) == 1 else 's', len(self.made), '' if len(self.made) == 1 else 's',
                  len(self.updated), len(self.unloaded), '' if len(self.unloaded) == 1 else 's')]
        if not (self.moved or self.made or self.updated or self.unloaded or self.restored or self.removed_nodes):
            out.append('Nothing changed: every graph is up to date with its layers.')
        if self.updated:
            out.append('Graphs brought up to date: %s.' % ', '.join(self.updated))
        if self.overrides:
            out.append('MoonShine Material Overrides made for nested masks: ' + ', '.join(self.overrides) + '.')
        if self.removed_nodes:
            out.append('%d node%s of layers that are gone taken out.' % (self.removed_nodes, '' if self.removed_nodes == 1 else 's'))
        for name in self.restored:
            out.append('Put back in the Shader Tree: %s.' % name)
        for name, why in self.left:
            out.append('Left in the Shader Tree: %s: %s.' % (name, why.rstrip('.')))
        for name, why in self.kept:
            out.append('Image clip kept: %s: %s.' % (name, why.rstrip('.')))
        out.extend(self.notes)
        return out


def on(item):
    return bool(channel(item, 'enable', 1)) and bool(channel(item, 'render', 1))


def texture_layer(item):
    return item.type not in NOT_LAYERS and not properties.is_material(item) and channel(item, 'effect', None) is not None


def effect_of(item):
    from .textures import EFFECT_ALIASES
    effect = channel(item, 'effect', '')
    return EFFECT_ALIASES.get(effect, effect)


def tagged(mask):
    """Whether a group is for some surfaces (a tag, a part, a selection set, items), not a plain group of layers."""
    kind, value = tag_kind(channel(mask, 'ptyp', '')), channel(mask, 'ptag', '')
    return bool(value) or kind not in ('', 'material') or bool(mask_items(mask))


def material_tags(item):
    """The material tags the groups above an item are for."""
    found = set()
    parent = item.parent
    while parent is not None and parent.type == 'mask':
        if tag_kind(channel(parent, 'ptyp', '')) == 'material' and channel(parent, 'ptag', ''):
            found.add(channel(parent, 'ptag', ''))
        parent = parent.parent
    return found


def apart(a, b):
    """Whether two items' groups are for different material tags, so that no polygon is in both."""
    ta, tb = material_tags(a), material_tags(b)
    return bool(ta) and bool(tb) and not (ta & tb)


def our_override(item):
    """Whether an item is a MoonShine Material Override this command made for a nested mask: it stands for the
    material's layers there, not for a material of its own."""
    if item.type != OVERRIDE_TYPE:
        return False
    graph = properties.peek(item).get('node_graph') or {}
    return bool((graph.get(transfer.META_KEY) or {}).get('override_of'))


def a_material(item):
    """A material of the Shader Tree's own (not one of this command's overrides)."""
    return properties.is_material(item) and not our_override(item)


def holds_material(mask):
    return any(a_material(item) and on(item) for item in layers.ordered_items(mask))


def opaque(material):
    """Whether a material covers what is under it whole: at full opacity, Normal, not inverted, its groups too."""
    if float(channel(material, 'opacity', 1)) != 1 or channel(material, 'blend', 'normal') != 'normal' or channel(material, 'invert', False):
        return False
    groups = layers.texture_groups(material, channel)
    return groups is not None and all(g['opacity'] == 1 and g['blend'] == 'normal' and not g['invert'] for g in groups)


def ancestors(item, render):
    found = []
    parent = item.parent
    while parent is not None and parent.id != render.id:
        found.append(parent)
        parent = parent.parent
    return found


def top_first(parent):
    return list(reversed(list(parent.children())))


class Row:
    """What of the Shader Tree a material is drawn with: its layers (those of its row alone), the nested masks among
    them for some of its surfaces, and what else reaches its surfaces (layers above its groups, masks of its groups,
    materials over it)."""

    def __init__(self, material, render):
        self.material = material
        self.layers = []          # its row's layer items
        self.nested = {}          # layer id -> the nested mask (for some surfaces) it is in
        self.shared = []          # layers above a group with its own material: they shade that material too
        self.foreign = []         # layers above its groups, which shade its surfaces too
        self.row_masks = []       # Group Masks and Layer Masks of its groups
        self.over = []            # materials above it that may share its surfaces and do not cover them whole
        parent = material.parent
        siblings = top_first(parent)
        index = next(i for i, item in enumerate(siblings) if item.id == material.id)
        boundary = False
        for item in reversed(siblings[:index]):
            if a_material(item) and on(item):
                break
            if item.type == 'mask':
                if not on(item):
                    continue
                if holds_material(item):
                    boundary = True
                    continue
                inner = [x for x in layers.ordered_items(item) if texture_layer(x)]
                if boundary:
                    self.shared += [x for x in inner if on(x)]
                    continue
                for x in inner:
                    self.layers.append(x)
                    chain = []
                    up = x.parent
                    while up is not None and up.id != parent.id:
                        chain.append(up)
                        up = up.parent
                    nested = [mask for mask in reversed(chain) if tagged(mask)]
                    if nested:
                        self.nested[x.id] = nested[0]
            elif texture_layer(item):
                if boundary and on(item):
                    self.shared.append(item)
                elif not boundary:
                    self.layers.append(item)
        for group in [parent] + ancestors(parent, render) if parent.id != render.id else []:
            if group.type != 'mask':
                break
            for child in group.children():
                if texture_layer(child) and on(child) and effect_of(child) == 'groupMask':
                    self.row_masks.append(child)
            if group.parent is not None:
                below = top_first(group.parent)
                at = next(i for i, item in enumerate(below) if item.id == group.id)
                if at + 1 < len(below) and texture_layer(below[at + 1]) and on(below[at + 1]) and effect_of(below[at + 1]) == 'layerMask':
                    self.row_masks.append(below[at + 1])
        for level in [material] + ancestors(material, render):
            if level.id == material.id:
                continue
            up = level.parent
            if up is None:
                break
            siblings = top_first(up)
            at = next(i for i, item in enumerate(siblings) if item.id == level.id)
            for item in siblings[:at]:
                if not on(item):
                    continue
                if a_material(item):
                    if not opaque(item):
                        self.over.append(item)
                elif item.type == 'mask':
                    if apart_mask(item, material):
                        continue
                    for x in layers.ordered_items(item):
                        if not on(x):
                            continue
                        if a_material(x):
                            if not opaque(x):
                                self.over.append(x)
                        elif texture_layer(x):
                            self.foreign.append(x)
                elif texture_layer(item):
                    self.foreign.append(item)


def apart_mask(mask, material):
    """Whether no polygon is both in a group's scope and in a material's: told by the material tags each scope's
    polygons carry (scope_tags)."""
    a, b = scope_tags(mask, True), scope_tags(material, False)
    return a is not None and b is not None and not (a & b)


# Each mesh's polygons' tags, for one run.
_SCOPES = {}
# Meshes with more polygons than this are not walked for their tags: their masks are taken to reach every surface.
WALKED_POLYGONS = 400000


def _mesh_tags(scene):
    """For each mesh: {(material tag, part, selection sets)} of its polygons (None where not walked), once for a run."""
    held = _SCOPES.get('meshes')
    if held is not None:
        return held
    found = {}
    for mesh in scene.items('mesh'):
        try:
            polygons = mesh.geometry.polygons
            if len(polygons) > WALKED_POLYGONS:
                found[mesh.id] = None
                continue
            rows = set()
            for polygon in polygons:
                tag, part, picks = (_tag(polygon, kind) for kind in (lx.symbol.i_POLYTAG_MATERIAL, lx.symbol.i_POLYTAG_PART, lx.symbol.i_POLYTAG_PICK))
                rows.add((tag, part, frozenset(p for p in picks.split(';') if p)))
            found[mesh.id] = rows
        except Exception:
            found[mesh.id] = None
    _SCOPES['meshes'] = found
    return found


def _tag(polygon, kind):
    try:
        return polygon.getTag(kind) or ''
    except LookupError:
        return ''


def scope_tags(item, inclusive):
    """The material tags of the polygons an item's groups (and the item itself where it is a group, inclusive) reach;
    None where that cannot be told (a mask for items, a mesh too heavy to walk)."""
    chain = ([item] if inclusive and item.type == 'mask' else []) + [p for p in ancestors(item, modo.Scene().renderItem) if p.type == 'mask']
    tests = []
    for mask in chain:
        kind, value = tag_kind(channel(mask, 'ptyp', '')), channel(mask, 'ptag', '')
        if mask_items(mask):
            return None
        if not value:
            continue
        if kind == 'material':
            tests.append(lambda row, v=value: row[0] == v)
        elif kind == 'part':
            tests.append(lambda row, v=value: row[1] == v)
        elif kind in ('selection set', 'pick'):
            tests.append(lambda row, v=value: v in row[2])
        else:
            return None
    meshes = _mesh_tags(modo.Scene())
    if any(rows is None for rows in meshes.values()):
        return None
    return frozenset(row[0] for rows in meshes.values() for row in rows if all(test(row) for test in tests))


# Reading layers whose image this command took out: the kit's own reading (layers.collect) is handed the image the
# layer's node names, and the layer as on, so that what it reads is what the layer would be with its image back.
_MISSING = object()


class _Value:
    def __init__(self, value):
        self.value = value

    def get(self, *args):
        return self.value


class _Clip:
    def __init__(self, identity, values, kind='videoStill'):
        self.id = identity
        self.name = values.get('name', identity)
        self.type = kind
        self._values = values

    def channel(self, name):
        return _Value(self._values[name]) if name in self._values else None


class _Folder:
    def __init__(self, identity, tiles, colorspace):
        self.id = identity
        self.name = identity
        self.type = 'imageFolder'
        self._clips = [_Clip('%s_%d' % (identity, number), {'filename': filename, 'udim': number, 'colorspace': colorspace})
                       for number, filename in tiles]

    def children(self):
        return list(self._clips)

    def channel(self, name):
        return None


class _Graph:
    def __init__(self, graph, extra):
        self._graph = graph
        self._extra = extra

    def forward(self, *args):
        return [item for item in self._graph.forward(*args) if item.type not in ('videoStill', 'imageFolder', 'videoSequence')] + [self._extra]

    def __getattr__(self, name):
        return getattr(self._graph, name)


class _Layer:
    """A layer as it would be with its image back: on, and linked to it."""

    def __init__(self, item, source, force_on=True):
        self._item = item
        self._source = source
        self._on = force_on

    def __getattr__(self, name):
        return getattr(self._item, name)

    def channel(self, name):
        if name == 'enable' and self._on:
            return _Value(True)
        return self._item.channel(name)

    def itemGraph(self, name):
        graph = self._item.itemGraph(name)
        source = self._source
        if name != 'shadeLoc' or source is None:
            return graph
        if source.get('tiles'):
            extra = _Folder('mrst_' + self._item.id, [(int(n), f) for n, f in source['tiles']], source.get('colorspace', '(default)'))
        elif source.get('sequence'):
            # An image sequence (shader_tree_clips.source_of_sequence), read with its settings.
            extra = _Clip('mrst_' + self._item.id, {'pattern': source['pattern'], 'firstFrame': source['first_frame'],
                                                    'lastFrame': source['last_frame'], 'startFrame': source['start_frame'],
                                                    'endBehavior': source['end_behavior'], 'alphaMode': source.get('alpha_mode', 1),
                                                    'colorspace': source.get('colorspace', '(default)')}, 'videoSequence')
        else:
            extra = _Clip('mrst_' + self._item.id, {'filename': source['filename'], 'colorspace': source.get('colorspace', '(default)'),
                                                    'alphaMode': source.get('alpha_mode', 1)})
        return _Graph(graph, extra)


# Clips that stand in for a scene's images, as Open Scene as MoonShine opens it (moonshine_open): {stand-in file, folded
# case: what the scene's clip named}.
PLACEHOLDERS = {}


def stood_in(clip):
    """The scene's own clip a stand-in clip is for (PLACEHOLDERS), or None."""
    if clip is None or not PLACEHOLDERS:
        return None
    import os
    return PLACEHOLDERS.get(os.path.normcase(os.path.abspath(str(channel(clip, 'filename', '') or ''))))


def placeholder_source(clip, folder=None):
    """A layer's image as source_of would give it, where its clip (or its Image Folder's) stands in for the scene's."""
    if clip is not None:
        held = stood_in(clip)
        if held is None:
            return None
        return {'filename': held['filename'], 'colorspace': channel(clip, 'colorspace', '(default)'), 'clip': held.get('name') or clip.name}
    if folder is not None:
        clips = sorted((i for i in folder.children() if i.type == 'videoStill'), key=lambda i: int(channel(i, 'udim', 1001)))
        held = [stood_in(i) for i in clips]
        if not clips or any(h is None for h in held):
            return None
        return {'tiles': [[int(channel(i, 'udim', 1001)), h['filename']] for i, h in zip(clips, held)],
                'colorspace': channel(clips[0], 'colorspace', '(default)'), 'folder': folder.name}
    return None


def image_of(layer):
    """(clip, folder) linked to an image layer."""
    try:
        linked = layer.itemGraph('shadeLoc').forward()
    except (LookupError, RuntimeError, AttributeError):
        return None, None
    clip = next((i for i in linked if i.type == 'videoStill'), None)
    # An image sequence clip is a layer's clip as a still is (shader_tree_clips).
    clip = clip or next((i for i in linked if i.type == 'videoSequence'), None)
    folder = next((i for i in linked if i.type == 'imageFolder'), None)
    return clip, folder


def source_of(layer):
    """What a layer's image is, for its node's record: its file (or its UDIM set's tiles, or its image sequence) and
    colour space."""
    clip, folder = image_of(layer)
    if clip is not None and clip.type == 'videoSequence':
        from .shader_tree_clips import source_of_sequence
        return source_of_sequence(clip, channel)
    if clip is not None:
        held = {'filename': channel(clip, 'filename', ''), 'colorspace': channel(clip, 'colorspace', '(default)'), 'clip': clip.name}
        if not int(channel(clip, 'alphaMode', 1)):
            held['alpha_mode'] = 0
        return held
    if folder is not None:
        clips = sorted((i for i in folder.children() if i.type == 'videoStill'), key=lambda i: int(channel(i, 'udim', 1001)))
        return {'tiles': [[int(channel(i, 'udim', 1001)), channel(i, 'filename', '')] for i in clips],
                'colorspace': channel(clips[0], 'colorspace', '(default)') if clips else '(default)', 'folder': folder.name}
    return None


def read_layers(scene, material, key, row_ids, sources, warnings):
    """layers.collect's dicts for these layers of a material, those whose image this command took out read with it back."""
    render = scene.renderItem
    value = host.material_values(material, warnings)
    real = layers.ordered_items(render)
    items = []
    for item in real:
        if item.id not in row_ids or item.type != 'imageMap':
            items.append(item)
            continue
        clip, folder = image_of(item)
        held = placeholder_source(clip, folder)
        if item.id in sources:
            # Moved before (and so off): read on, with its image as its node has it where its clip is gone.
            items.append(_Layer(item, sources[item.id] if (clip, folder) == (None, None) or held else None))
        elif held:
            # Opened by Open Scene as MoonShine: its clip a stand-in for the image the scene names.
            items.append(_Layer(item, held, force_on=False))
        else:
            items.append(item)
    proxied = [item.id for item in items if isinstance(item, _Layer) and item._on]
    with layers.held_tree():
        key_ordered = ('ordered', render.id)
        before = layers._HELD.get(key_ordered, None)
        layers._HELD[key_ordered] = items
        channels = host._CHANNELS
        kept = {}
        if channels is not None:
            for identity in proxied:
                kept[identity] = channels.get((identity, 'enable'), _MISSING)
                channels[(identity, 'enable')] = True
        try:
            layers.collect(scene, {key: value}, warnings, layer_filter=set(row_ids), material_key=key)
        finally:
            if before is None:
                layers._HELD.pop(key_ordered, None)
            else:
                layers._HELD[key_ordered] = before
            if channels is not None:
                for identity, held in kept.items():
                    if held is _MISSING:
                        channels.pop((identity, 'enable'), None)
                    else:
                        channels[(identity, 'enable')] = held
    found = []
    names = {item.id: item.name for item in items}
    for layer in value.get('layers') or []:
        layer = dict(layer, name=names.get(layer['identity'], layer['identity']))
        item = next((i for i in items if i.id == layer['identity']), None)
        if layer.get('kind') == 'imageMap' and item is not None:
            layer['_source'] = item._source or source_of(item._item) if isinstance(item, _Layer) else source_of(item)
        found.append(layer)
    return value, found


def alpha_of(path):
    from . import textures
    try:
        tiles = textures.source_tiles(path)
    except (OSError, ValueError):
        return None
    if not tiles:
        return None
    answers = {transfer.file_alpha(str(p)) for p in tiles.values()}
    return True if True in answers else (None if None in answers else False)


def beneath(material, tree):
    """The materials under a material in the Shader Tree that may reach its surfaces: the rows of its stack as a render
    reads them, which it covers but which still count in how its highlight is drawn (moonshine.specular_ceiling)."""
    position = next(i for i, item in enumerate(tree) if item.id == material.id)
    found = []
    for item in tree[position + 1:]:
        if item.type != 'advancedMaterial' or not on(item) or layers.texture_groups(item, channel) is None:
            continue
        a, b = scope_tags(item, False), scope_tags(material, False)
        if a is not None and b is not None and not (a & b):
            continue
        found.append(item)
    return found


# What a stack's rows keep in a graph's record (transfer.META_KEY 'stack'): the material as Modo had it, without its layers.
STRIPPED = ('layers', 'textures', 'material_stack', 'node_graph', 'native_dependencies', 'baked_effects')


def stack_rows(scene, material, tree):
    """The rows of a Modo material's stack as a render reads them (layers.material_stack), with no layers: the material over
    the materials beneath it, which it covers but which still count in how its highlight is drawn."""
    candidates = [material] + beneath(material, tree)
    rows = layers.material_stack(scene, candidates, [], 'shader_tree_transfer', {item.id for item in candidates})
    return [{key: value for key, value in row.items() if key not in STRIPPED} for row in rows]


def output_values(values):
    """A Modo material's output values as connect() read them, typed as DwaBaseMaterial's controls (held to their limits)."""
    from . import shader_library
    schema = shader_library.catalog()['DwaBaseMaterial']['attributes']
    kept = {}
    for name, held in values.items():
        try:
            kept[name] = shader_library.typed(held, schema[name])
        except ValueError:
            low, high = schema[name].get('min'), schema[name].get('max')
            try:
                if isinstance(held, list):
                    held = [min(float(str(high).rstrip('f')), max(float(str(low).rstrip('f')), v)) if low is not None and high is not None else v for v in held]
                else:
                    if low is not None:
                        held = max(float(str(low).rstrip('f')), held)
                    if high is not None:
                        held = min(float(str(high).rstrip('f')), held)
                kept[name] = shader_library.typed(held, schema[name])
            except (ValueError, TypeError):
                continue
    return kept


def wire_modo(made, material, rows, found):
    """A Modo material's plan wired as its MoonRay text has it (transfer.connect): its moved layers in its row. Returns its
    output's values."""
    moving = set(made.moved)
    rows = [dict(row) for row in rows]
    rows[-1] = dict(rows[-1], layers=[layer for layer in found if layer['identity'] in moving], textures={})
    lines = transfer.marked_text(rows, made.keys)
    return transfer.connect(made, material.id, lines, '/modo/material/0')


def refusal(material, value, row):
    """Why a Modo material cannot become a graph as it renders now, or None. As a graph its row is mixed with what is
    under it as one shader, not channel by channel, and the Shader Tree layers left on it would be drawn as a native
    material's are: so it moves whole, or not at all, and only where nothing but its own layers reaches its surfaces."""
    from . import absorption
    if float(value.get('layer_opacity', 1)) != 1 or value.get('layer_blend', 'normal') != 'normal' or value.get('layer_invert'):
        return 'the material is laid on at another opacity or blend than 100% Normal'
    groups = layers.texture_groups(material, channel) or []
    if any(g['opacity'] != 1 or g['blend'] != 'normal' or g['invert'] for g in groups):
        return 'a group it is in is at another opacity or blend than 100% Normal, or inverted'
    if row.row_masks:
        return 'its group is masked (%s)' % ', '.join(item.name for item in row.row_masks[:3])
    if row.foreign:
        return 'layers above its group shade it too (%s)' % ', '.join(item.name for item in row.foreign[:3])
    if row.shared:
        return 'layers above a group with a material of its own shade both (%s)' % ', '.join(item.name for item in row.shared[:3])
    if row.over:
        return 'a material over it that does not cover it whole (%s)' % ', '.join(item.name for item in row.over[:3])
    if len({mask.id for mask in row.nested.values()}) > 1:
        return 'its layers are in more than one nested mask, which may share surfaces'
    if absorption.enabled(value):
        return 'its glass absorbs light through its volume, which a graph material does not'
    if float(value.get('displacement_value', 0)):
        return 'it is displaced by its Displacement value'
    return None


class Job:
    def __init__(self, material):
        self.material = material
        self.graph = None
        self.created = False
        self.settings = None
        self.override = None      # (nested mask, graph) for a nested mask's override
        self.moved = []
        self.left = []


class _Quiet:
    """No progress bar: nothing is shown, and nothing is cancelled."""
    def step(self, *args):
        pass

    def stage(self, text, start, end):
        return self

    def hold(self):
        pass


def run(progress=None):
    """Move the scene's Shader Tree images into MoonShine graphs (see the module's description); the Report.
    progress: a shader_tree_dialog.Progress (the one showing, by default). Its Cancel stops the run while the scene is
    still being read, and nothing has been changed (shader_tree_dialog.Cancelled); from the first change on it runs to
    the end."""
    from . import shader_tree_dialog
    progress = progress or shader_tree_dialog.CURRENT or _Quiet()
    scene = modo.Scene()
    report = Report()
    render = scene.renderItem
    _SCOPES.clear()
    progress.step('Reading the scene...', 0.0, 1.0)
    with host.held_channels(), layers.held_tree():
        tree = list(layers.ordered_items(render))
        by_id = {item.id: item for item in tree}
        above = layers.above_shader(render)
        sources, overrides = {}, {}
        for item in tree:
            if not properties.is_material(item):
                continue
            settings = properties.read(item)
            graph = settings.get('node_graph') if material_override.enabled(settings) else None
            if not graph:
                continue
            for identity, record in transfer.our_layers(graph).items():
                if record.get('source'):
                    sources.setdefault(identity, record['source'])
            meta = graph.get(transfer.META_KEY) or {}
            if item.type == OVERRIDE_TYPE and meta.get('override_of'):
                overrides[item.id] = meta
        jobs = []
        materials = [item for item in tree if item.type == 'advancedMaterial' and on(item)]
        reading = progress.stage('Materials:', .05, .8)
        for index, material in enumerate(materials):
            reading.step('%d of %d, %s' % (index + 1, len(materials), material.name), index, len(materials))
            top = material
            while top.parent is not None and top.parent.id != render.id:
                top = top.parent
            if top.id in above or layers.texture_groups(material, channel) is None:
                continue
            job = read_job(scene, material, render, sources, report)
            if job is not None:
                jobs.append(job)
    progress.hold()
    # The environments' layers into their own graphs (shader_tree_environment), their clips unloaded with the rest.
    from . import shader_tree_environment
    environment_layers = shader_tree_environment.run(scene, report)
    write(scene, jobs, sources, overrides, by_id, report, progress, environment_layers)
    return report


def staying(found, identity):
    """The reason a layer stays whatever the rest does (transfer.STAYING), or None."""
    effect = next((layer.get('effect') for layer in found if layer['identity'] == identity), None)
    return transfer.STAYING.get(effect)


def read_job(scene, material, render, sources, report):
    settings = properties.read(material)
    graph = settings.get('node_graph') if material_override.enabled(settings) else None
    if settings.get('materialx_override'):
        return None
    row = Row(material, render)
    warnings = []
    ids = [item.id for item in row.layers]
    moving_before = [identity for identity in transfer.our_layers(graph)] if graph else []
    if not ids and not moving_before:
        return None
    meta = dict((graph or {}).get(transfer.META_KEY) or {})
    if graph:
        root = graph['nodes'].get(graph.get('root'), {})
        if root.get('type') != 'DwaBaseMaterial':
            if ids:
                report.left.append((material.name, 'its graph is a %s, not a DwaBaseMaterial; its layers stay' % root.get('type')))
            return None
        profile = meta.get('profile', 'native')
    elif material_override.enabled(settings) and settings.get('native_shader'):
        if settings['native_shader'] != 'DwaBaseMaterial':
            if ids:
                report.left.append((material.name, 'it is a %s, not a DwaBaseMaterial; its layers stay' % settings['native_shader']))
            return None
        profile = 'native'
    else:
        profile = 'modo'
    key = 'shader_tree_transfer:' + material.id
    value, found = read_layers(scene, material, key, ids, sources, warnings)
    names = {item.id: item.name for item in row.layers}
    read_ids = {layer['identity'] for layer in found}
    unread = {}
    for item in row.layers:
        if item.id in read_ids:
            continue
        live = on(item) or (item.id in sources and item.type == 'imageMap')
        if not live:
            continue
        why = next((w.split(': ', 1)[1] for w in warnings if w.startswith('Layer %s:' % item.name)), None) or 'the kit does not read it'
        unread[item.id] = (effect_of(item), why)
    first = profile == 'modo' and not graph
    job = Job(material)
    if first:
        why = refusal(material, value, row)
        if why is None and unread:
            identity, (effect, reason) = next(iter(unread.items()))
            why = '%s: %s' % (names.get(identity, identity), reason)
        if why is not None:
            if any(layer.get('kind') != 'constant' for layer in found):
                report.left.append((material.name, why))
            return None
        from .graph import defaults_for
        try:
            rows = stack_rows(scene, material, list(layers.ordered_items(render)))
        except (ValueError, KeyError) as exc:
            report.left.append((material.name, 'its stack could not be read (%s)' % exc))
            return None
        meta = {'profile': 'modo', 'material': material.id, 'bases': defaults_for(value),
                'post': {'bump_strength': value.get('bump_strength', .005)}, 'stack': rows}
        graph = nodes.new('DwaBaseMaterial', {})
        job.created = True
    else:
        if not graph:
            graph = nodes.new('DwaBaseMaterial', dict(settings.get('native_parameters') or {}))
            job.created = True
        if 'bases' not in meta:
            from .graph import defaults_for
            meta.update(profile=profile, material=material.id, bases=defaults_for(value),
                        post={'diffuse_amount': value.get('diffuse_amount', 1.0), 'emission_amount': value.get('emission_amount', 1.0),
                              'bump_strength': value.get('bump_strength', .005)})
    bases, post = meta['bases'], meta['post']
    if not any(layer.get('kind') != 'constant' for layer in found) and not moving_before:
        return None
    blocked = {effect: '%s: %s' % (names.get(identity, identity), why) for identity, (effect, why) in unread.items()}
    for item in row.foreign + row.shared:
        blocked.setdefault(effect_of(item), 'the layer %s above its group shades it too' % item.name)
    root = graph['nodes'][graph['root']]
    wired = {name for name, source in (root.get('inputs') or {}).items()
             if source in graph['nodes'] and not transfer.ours(source, graph['nodes'][source])}
    nested = {identity: mask for identity, mask in row.nested.items()}
    masks = {mask.id: mask for mask in nested.values()}
    if len(masks) > 1:
        for identity in nested:
            effect = next((layer['effect'] for layer in found if layer['identity'] == identity), None)
            if effect:
                blocked.setdefault(effect, 'its layers are in more than one nested mask, which may share surfaces')
    own = [layer for layer in found if layer['identity'] not in nested]
    try:
        made = transfer.plan(material.id, own if len(masks) <= 1 else found, bases, 'modo' if meta['profile'] == 'modo' else 'native',
                             post, alpha_of, blocked, wired, strict=first)
        holding = [(i, w) for i, w in made.left if staying(found, i) is None]
        if first and holding:
            raise transfer.Refused('; '.join('%s: %s' % (names.get(i, i), w) for i, w in holding))
    except transfer.Refused as exc:
        if first:
            report.left.append((material.name, str(exc)))
            return None
        raise
    modo = meta['profile'] == 'modo' and meta.get('stack')
    if modo and made.keys:
        try:
            values = wire_modo(made, material, meta['stack'], found)
        except (transfer.NotConstant, ValueError, KeyError) as exc:
            report.left.append((material.name, 'its MoonRay material could not be followed into a graph (%s); its layers stay' % exc))
            return None
        if first:
            # The colour as Modo holds it, not as the text rounds it: Modo's diffuse follows it (material_diffuse), and a
            # colour rounded once would be written again at the next run.
            for key in ('albedo', 'metallic_color'):
                held = values.get(key)
                if isinstance(held, list) and all(abs(a - b) < 1e-9 for a, b in zip(held, value.get('color', []))):
                    values[key] = [float(v) for v in value['color']]
            graph = nodes.new('DwaBaseMaterial', output_values(values))
    job.moved = list(made.moved)
    job.left = [(names.get(i, i), w) for i, w in made.left]
    job.graph = transfer.merged(graph, made, meta, created=job.created)
    job.settings = settings
    if len(masks) == 1:
        mask = next(iter(masks.values()))
        try:
            whole = transfer.plan(material.id, found, bases, 'modo' if meta['profile'] == 'modo' else 'native', post, alpha_of, blocked, wired,
                                  strict=first)
        except transfer.Refused as exc:
            whole = None
            if first:
                report.left.append((material.name, str(exc)))
                return None
        if whole is not None and modo and whole.keys:
            try:
                wire_modo(whole, material, meta['stack'], found)
            except (transfer.NotConstant, ValueError, KeyError) as exc:
                report.left.append((material.name, 'its nested mask could not be followed into a graph (%s)' % exc))
                return None
        if whole is not None:
            moved = set(whole.moved)
            holding = [(i, w) for i, w in whole.left if staying(found, i) is None]
            if first and holding:
                report.left.append((material.name, '; '.join('%s: %s' % (names.get(i, i), w) for i, w in holding)))
                return None
            base = transfer.merged(job.graph, transfer.Plan(), {})
            base.pop(transfer.META_KEY, None)
            override_meta = {'profile': meta['profile'], 'override_of': material.id, 'group': mask.id, 'bases': bases, 'post': post}
            existing = next((child for child in mask.children() if our_override(child)), None)
            previous = properties.read(existing).get('node_graph') if existing is not None else None
            if previous:
                # Where this command's nodes stood in the override's graph, they stay.
                for identity, node in previous['nodes'].items():
                    if transfer.ours(identity, node) and 'position' in node:
                        base['nodes'].setdefault(identity, dict(node))
            made_override = transfer.merged(base, whole, override_meta, created=previous is None)
            job.override = (mask, made_override)
            job.moved = sorted(set(job.moved) | {i for i in moved if i in nested})
            job.left += [(names.get(i, i), w) for i, w in whole.left if i in nested]
    return job


def write(scene, jobs, sources, overrides, by_id, report, progress=None, environment_layers=None):
    progress = progress or _Quiet()
    building = progress.stage('Building graphs:', .8, .95)
    moved_now = set()
    for index, job in enumerate(jobs):
        building.step('%d of %d, %s' % (index + 1, len(jobs), job.material.name), index, len(jobs))
        material = job.material
        settings = job.settings if job.settings is not None else properties.read(material)
        before = settings.get('node_graph') if material_override.enabled(settings) else None
        written = material_override.synchronize(settings, job.graph)
        if rewritten(material, written):
            (report.made if job.created else report.updated).append(material.name)
            if before:
                old = {i for i, n in before['nodes'].items() if transfer.ours(i, n)}
                new = {i for i, n in job.graph['nodes'].items() if transfer.ours(i, n)}
                report.removed_nodes += len(old - new)
        override_of_material = [identity for identity, meta in overrides.items() if meta.get('override_of') == material.id]
        if job.override is not None:
            mask, graph = job.override
            item = next((by_id[i] for i in override_of_material if i in by_id and by_id[i].parent is not None and by_id[i].parent.id == mask.id), None)
            if item is None:
                item = scene.addItem(OVERRIDE_TYPE, name='MoonShine Material Override - %s (%s)' % (material.name, mask.name))
                item.setParent(mask, 0)
                report.overrides.append(item.name)
                previous = None
            else:
                previous = properties.read(item).get('node_graph')
            if rewritten(item, material_override.synchronize(properties.read(item) if previous is not None else {}, graph)) and previous is not None:
                report.updated.append(item.name)
            override_of_material = [i for i in override_of_material if i != item.id]
        for identity in override_of_material:
            # A nested mask's override this command made, whose mask has no layers to move any more.
            if identity in by_id:
                remove(scene, by_id[identity])
        for identity in job.moved:
            layer = by_id.get(identity)
            if layer is None:
                continue
            moved_now.add(identity)
            if channel(layer, 'enable', 1):
                lx.eval('item.channel textureLayer$enable false item:{%s}' % layer.id)
                report.moved.append((layer.name, material.name))
        for name, why in job.left:
            report.left.append((name, why))
    # Layers whose image this command took out, moved nowhere now: put back as they were.
    for identity, source in sources.items():
        if identity in moved_now or identity not in by_id:
            continue
        layer = by_id[identity]
        if image_of(layer) != (None, None):
            continue
        if restore(scene, layer, source):
            report.restored.append(layer.name)
        else:
            report.left.append((layer.name, 'its image %s could not be loaded again; load it by hand' % (source.get('filename') or source.get('pattern') or 'set')))
    progress.step('Unloading image clips...', .95, 1.0)
    environment_layers = environment_layers or {}
    # The lights' image layers (shader_tree_lights), a clip they share with the layers moved here taken out with theirs.
    try:
        from . import shader_tree_lights
        lights = shader_tree_lights.run(scene, also_moved=moved_now | set(environment_layers))
        if lights.moved or lights.left or lights.unloaded or lights.restored:
            report.notes.extend(lights.lines())
        report.unloaded.extend(lights.unloaded)
    except Exception as exc:
        report.notes.append('Lights: their image layers were not moved (%s).' % exc)
    unload(scene, moved_now | set(environment_layers), dict(by_id, **environment_layers), report)
    if PLACEHOLDERS:
        # Opened by Open Scene as MoonShine: the stand-in clips that stay load their own images, as the scene had them.
        for clip in list(scene.items('videoStill')):
            held = stood_in(clip)
            if held is not None:
                lx.eval('item.channel videoStill$filename {%s} item:{%s}' % (held['filename'], clip.id))
                report.notes.append('Image clip %s loads its image: a layer that stays in the Shader Tree, or something else, uses it.' % clip.name)


def tag_text(item):
    try:
        return item.readTag(properties.TAG)
    except (LookupError, RuntimeError):
        return None


def rewritten(item, values):
    """Write a material's settings; whether that changed them (properties.write leaves settings that are the same)."""
    before = tag_text(item)
    properties.write(item, values)
    return tag_text(item) != before


def restore(scene, layer, source):
    """Load a layer's image (or image sequence) again and switch it on (a UDIM set is not made again)."""
    if source.get('sequence'):
        clip = restore_sequence(scene, source)
        if clip is None:
            return False
    else:
        if source.get('tiles') or not source.get('filename'):
            return False
        before = {item.id for item in scene.items('videoStill')}
        try:
            lx.eval('clip.addStill {%s}' % source['filename'])
        except RuntimeError:
            return False
        made = [item for item in scene.items('videoStill') if item.id not in before]
        if not made:
            return False
        clip = made[0]
    try:
        if source.get('colorspace') and source['colorspace'] != '(default)':
            lx.eval('item.channel %s$colorspace {%s} item:{%s}' % (clip.type, source['colorspace'], clip.id))
        if 'alpha_mode' in source:
            lx.eval('item.channel %s$alphaMode %d item:{%s}' % (clip.type, int(source['alpha_mode']), clip.id))
    except RuntimeError:
        pass
    lx.eval('select.item {%s} set' % layer.id)
    lx.eval('texture.setIMap {%s}' % clip.name)
    lx.eval('item.channel textureLayer$enable true item:{%s}' % layer.id)
    return True


def restore_sequence(scene, source):
    """An image sequence clip loaded again as it was recorded (shader_tree_clips.source_of_sequence), or None."""
    from .shader_tree_clips import first_file
    found = first_file(source)
    if found is None:
        return None
    before = {item.id for item in scene.items('videoSequence')}
    try:
        lx.eval('clip.addSequence {%s}' % found)
    except RuntimeError:
        return None
    made = [item for item in scene.items('videoSequence') if item.id not in before]
    if not made:
        return None
    clip = made[0]
    for name, key in (('firstFrame', 'first_frame'), ('lastFrame', 'last_frame'), ('startFrame', 'start_frame')):
        lx.eval('item.channel videoSequence$%s %d item:{%s}' % (name, int(source[key]), clip.id))
    lx.eval('item.channel videoSequence$endBehavior {%s} item:{%s}' % (source.get('end_behavior', 'hold'), clip.id))
    return clip


def users(item):
    """The items that link to a clip or Image Folder through the Shader Tree's links."""
    try:
        return list(item.itemGraph('shadeLoc').reverse())
    except (LookupError, RuntimeError, AttributeError):
        return []


def unload(scene, moved, by_id, report):
    """Take out the clips of moved layers that nothing else uses: a clip another layer still uses, or anything else,
    is kept and said."""
    seen = set()
    for identity in sorted(moved):
        layer = by_id.get(identity)
        if layer is None:
            continue
        clip, folder = image_of(layer)
        target = folder or clip
        if target is None or target.id in seen:
            continue
        seen.add(target.id)
        if folder is not None and clip is None:
            parent = None
        else:
            parent = clip.parent if clip is not None and clip.parent is not None and clip.parent.type == 'imageFolder' else None
        holders = users(target) + (users(parent) if parent is not None else [])
        others = [item for item in holders if item.id not in moved]
        if others:
            names = ', '.join(sorted({item.name for item in others})[:3])
            report.kept.append((target.name, 'also used by %s' % names))
            continue
        if folder is not None:
            name = folder.name
            for child in list(folder.children()):
                if child.type == 'videoStill':
                    remove(scene, child)
            remove(scene, folder)
            report.unloaded.append(name)
        else:
            name = clip.name
            remove(scene, clip)
            report.unloaded.append(name)


def remove(scene, item):
    lx.eval('select.item {%s} set' % item.id)
    lx.eval('!item.delete')
