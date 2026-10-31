"""Automatic Presence Shadows, a choice in MoonRay's preferences (off unless chosen): a scene's see-through surfaces cast
shadows only as much as they are there wherever a material is cut out by a map, and solid ones where none is, MoonRay's
quicker default. While it is on, the Presence Shadows in Render Settings and each light's own are greyed and not read.
Without it a label's cut-out frame shades the surface under it, as MoonRay does in every mode."""
from . import options


def automatic():
    """Whether it is chosen. Not where the preferences cannot be read, outside Modo."""
    from .cache_folder import _setting
    return str(_setting('presence_shadows_auto', 'false', 'false')).lower() in ('true', '1')


def cuts_out(material):
    """A Shader Tree Stencil layer, or a graph with something wired into a material's presence."""
    layers = material.get('layers')
    if layers is None:
        layers = [{'effect': key} for key in material.get('textures', {})]
    if any(layer.get('effect') == 'stencil' for layer in layers):
        return True
    graph = material.get('node_graph') or {}
    rows = list(graph.get('nodes', {}).values()) + list(graph.get('overrides') or [])
    return any('presence' in (row.get('inputs') or {}) for row in rows)


def in_use(scene):
    return any(cuts_out(material) for material in scene.get('materials', {}).values())


def render_values(scene):
    """The scene's render settings as the renderers are given them."""
    values = options.render_values(scene.get('render_settings', {}))
    if automatic():
        values['enable_presence_shadows'] = 1 if in_use(scene) else 0
    return values
