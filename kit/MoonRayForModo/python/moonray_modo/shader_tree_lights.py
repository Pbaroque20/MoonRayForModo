"""A light's own Shader Tree images, for Move Shader Tree Textures to MoonShine Graphs: the Image Map layers under a
Modo light (beside its Light Material, as Modo puts them: a picture or a colour on the light), and its IES profile.

What the kit draws of them, in MoonRay, XPU2 and MoonLightIPR alike (host.snapshot's lights):
  - a layer of effect Light Color, as Modo's own renderer draws it (light_images): a light with no size is the image's
    one colour where it shines from, an area light the image laid across it; other effects, and constant, gradient or
    procedural layers on a light, are not drawn (as before);
  - a Photometric light by its IES profile (ies_lights), the file its filename channel names: no clip is loaded for it;
  - a MoonRay light item's picture (its texture, a cookie light filter's) is a file it names: no clip is loaded for it.
So an Image Map layer of a light moves as a record that names its image (path only, as an Image node does: the light's
entry in the scene's light settings, production > lights > <light> > shader_tree_images), its layer switched off and its
clip taken out; light_images reads the switched-off layer with its record's image, and the light renders as before.
Run again, a record whose layer is gone is dropped, and a moved layer switched on again by hand is read anew. restore()
puts the layers back. A layer that is not an image, a light switched off, and IES profiles (nothing of Modo's to take
out) stay, each said with why. All in the one undoable step of the command that calls run(); the writes are lx.eval and
properties.write.

Nothing of Modo here but run(), restore() and what they call: plan() decides from plain dicts, for tests."""
import copy

RECORD_KEY = 'shader_tree_images'
NOT_LAYERS = ('lightMaterial', 'mask', 'txtrLocator')
LIGHT_IMAGE_NOTE = ("a light's Shader Tree image is drawn by the kit from its record, its image read from the file the "
                    "record names (MoonRay, XPU2 and MoonLightIPR alike); moved, the light renders as before")
IES_NOTE = ('an IES profile is a file the Photometric light names, with no clip to take out; the kit draws the light by '
            'its profile from that file')


class Report:
    def __init__(self):
        self.moved = []          # (layer name, light name)
        self.left = []           # (layer or light name, why)
        self.unloaded = []       # clips taken out
        self.kept = []           # (clip name, why)
        self.restored = []       # layers put back
        self.dropped = []        # records whose layer is gone
        self.notes = []

    def lines(self):
        out = ["Lights: %d image layer%s moved, %d image clip%s unloaded." % (
            len(self.moved), '' if len(self.moved) == 1 else 's', len(self.unloaded), '' if len(self.unloaded) == 1 else 's')]
        for layer, light in self.moved:
            out.append('Moved: %s (light %s).' % (layer, light))
        for name in self.restored:
            out.append('Put back on its light: %s.' % name)
        for name in self.dropped:
            out.append('Record dropped, its layer is gone: %s.' % name)
        for name, why in self.left:
            out.append('Left on the light: %s: %s.' % (name, why.rstrip('.')))
        for name, why in self.kept:
            out.append('Image clip kept: %s: %s.' % (name, why.rstrip('.')))
        out.extend(self.notes)
        return out


def plan(light, layers, records=None):
    """What moves of one light's layers: ([layer dicts that move], [(layer name, why) that stay], [records kept]).

    light: {'id', 'name', 'type', 'on', 'ies'}. layers: {'id', 'name', 'type', 'on', 'effect', 'source'} for each
    texture layer under the light (source: shader_tree_scene.source_of's, None for a layer with no image). records: the
    light's records from an earlier run ({'layer', ...})."""
    moving, left = [], []
    records = list(records or [])
    present = {layer['id'] for layer in layers}
    kept = [record for record in records if record.get('layer') in present]
    if light.get('ies'):
        left.append((light['name'], IES_NOTE))
    if not light.get('on', True):
        for layer in layers:
            if layer.get('on') and layer['type'] == 'imageMap':
                left.append((layer['name'], 'its light is switched off'))
        return moving, left, kept
    for layer in layers:
        if layer['type'] != 'imageMap':
            if layer.get('on'):
                left.append((layer['name'], 'a %s layer, not an image: it has no clip to take out' % layer['type']))
            continue
        if not layer.get('on'):
            continue  # off, or moved before (its record kept)
        if not layer.get('source'):
            left.append((layer['name'], 'it has no image'))
            continue
        moving.append(layer)
    return moving, left, kept


def record(layer, light):
    """A moved layer's record: what it was and the image it named (path only)."""
    return {'layer': layer['id'], 'name': layer['name'], 'light': light['id'], 'effect': layer.get('effect', ''),
            'opacity': float(layer.get('opacity', 1.0)), 'blend': layer.get('blend', 'normal'), 'source': copy.deepcopy(layer['source'])}


def merged_settings(settings, light_id, records):
    """The scene's settings with a light's records (none: its entry's records taken out)."""
    settings = copy.deepcopy(settings or {})
    production = settings.setdefault('production', {})
    lights = production.setdefault('lights', {})
    entry = dict(lights.get(light_id) or {})
    if records:
        entry[RECORD_KEY] = records
    else:
        entry.pop(RECORD_KEY, None)
    if entry:
        lights[light_id] = entry
    else:
        lights.pop(light_id, None)
    return settings


# Modo.
def light_layers(light):
    """The texture layers under a light (beside its Light Material, in groups there), top first."""
    from .host import channel
    found = []

    def walk(parent):
        for item in reversed(list(parent.children())):
            if item.type == 'mask':
                walk(item)
                continue
            if item.type in NOT_LAYERS or channel(item, 'effect', None) is None:
                continue
            found.append(item)
    walk(light)
    return found


def read_light(light):
    from .host import channel, render_visible
    from . import shader_tree_scene
    on = render_visible(light)
    held = {'id': light.id, 'name': light.name, 'type': light.type, 'on': on,
            'ies': str(channel(light, 'filename', '') or '') if light.type == 'photometryLight' else ''}
    layers = []
    for item in light_layers(light):
        source = shader_tree_scene.source_of(item) if item.type == 'imageMap' else None
        layers.append({'id': item.id, 'name': item.name, 'type': item.type, 'item': item,
                       'on': bool(channel(item, 'enable', 1)) and bool(channel(item, 'render', 1)),
                       'effect': str(channel(item, 'effect', '') or ''), 'opacity': float(channel(item, 'opacity', 1)),
                       'blend': str(channel(item, 'blend', 'normal')), 'source': source})
    return held, layers


def run(scene=None, also_moved=()):
    """Move the lights' Shader Tree images (see the module's description); the Report. also_moved: the identities of
    layers moved in the same step by the materials' run (shader_tree_scene), so that a clip a light's layer shares with
    them is taken out too."""
    import lx
    import modo
    from . import properties, shader_tree_scene
    scene = scene or modo.Scene()
    report = Report()
    settings = properties.scene_settings()
    stored = (settings.get('production') or {}).get('lights') or {}
    changed = settings
    moved_ids, by_id = set(), {}
    for light in scene.items('light'):
        held, layers = read_light(light)
        records = list((stored.get(light.id) or {}).get(RECORD_KEY) or [])
        moving, left, kept = plan(held, layers, records)
        for record_ in records:
            if record_ not in kept:
                report.dropped.append(record_.get('name') or record_.get('layer'))
        report.left += left
        new = [r for r in kept if not any(layer['id'] == r['layer'] for layer in moving)]
        for layer in moving:
            new.append(record(layer, held))
            item = layer['item']
            by_id[item.id] = item
            moved_ids.add(item.id)
            lx.eval('item.channel textureLayer$enable false item:{%s}' % item.id)
            report.moved.append((layer['name'], light.name))
        if new != records:
            changed = merged_settings(changed, light.id, new)
    if changed is not settings:
        properties.write(scene.renderItem, changed)
    # Layers moved by the materials' run count as moved here: not looked at (not in by_id), but not a clip's other user.
    shader_tree_scene.unload(scene, moved_ids | set(also_moved), by_id, report)
    if not report.moved and not report.dropped:
        report.notes.append('Nothing changed on the lights.')
    if report.moved:
        report.notes.append('Moved: ' + LIGHT_IMAGE_NOTE + '.')
    return report


def restore(scene=None):
    """Put every moved light layer back: its image loaded again, the layer on, its record taken out; the Report."""
    import modo
    from . import properties, shader_tree_scene
    scene = scene or modo.Scene()
    report = Report()
    settings = properties.scene_settings()
    stored = (settings.get('production') or {}).get('lights') or {}
    changed = settings
    for light_id, entry in stored.items():
        records = (entry or {}).get(RECORD_KEY) or []
        if not records:
            continue
        left = []
        for held in records:
            try:
                layer = scene.item(held['layer'])
            except LookupError:
                report.dropped.append(held.get('name') or held['layer'])
                continue
            if shader_tree_scene.image_of(layer) != (None, None):
                from .host import channel
                if not channel(layer, 'enable', 1):
                    import lx
                    lx.eval('item.channel textureLayer$enable true item:{%s}' % layer.id)
                report.restored.append(layer.name)
            elif shader_tree_scene.restore(scene, layer, held['source']):
                report.restored.append(layer.name)
            else:
                left.append(held)
                report.left.append((layer.name, 'its image could not be loaded again; load it by hand'))
        changed = merged_settings(changed, light_id, left)
    if changed is not settings:
        properties.write(scene.renderItem, changed)
    return report
