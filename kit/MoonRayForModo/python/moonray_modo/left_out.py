"""What of a Modo scene is not drawn as Modo has it, said in Notices rather than dropped with no word. No Modo: each takes what
was read."""

# Modo's material kinds the plugin reads nothing of, by their item types, and what each is called.
UNREAD_MATERIALS = {'unrealShader': 'Unreal', 'unityShader': 'Unity', 'glTFShader': 'glTF', 'AxFShader': 'AxF', 'Substance': 'Substance',
                    'matcapShader': 'Matcap', 'material.celShader': 'Cel', 'material.celEdges': 'Cel Edges', 'material.halftone': 'Halftone',
                    'material.iridescence': 'Iridescence', 'material.skinMaterial': 'Skin', 'material.thinfilm': 'Thin Film',
                    'material.hairMaterial': 'Hair'}


def unread_material(item, channel):
    """The notice for a Shader Tree item of a kind of material the plugin does not read, or None."""
    label = UNREAD_MATERIALS.get(item.type)
    if label is None or not channel(item, 'enable', 1):
        return None
    return "%s: Modo's %s material is left out." % (item.name, label)


def group_blends(masks, channel):
    """The notices for group masks whose blend mode the plugin does not have (layers.texture_groups draws them as Normal)."""
    from .layers import BLENDS
    return ['Group %s: its blend mode %s is drawn as Normal.' % (mask.name, channel(mask, 'blend', 'normal'))
            for mask in masks if channel(mask, 'blend', 'normal') not in BLENDS]


def asked_vertex_maps(value):
    """The vertex maps that materials ask for, by name: each Weight Map Texture layer's (procedurals.vertex_map), however deep."""
    if isinstance(value, dict):
        named = {str(value['vmap'])} if value.get('vmap') else set()
        return named.union(*[asked_vertex_maps(held) for held in value.values()])
    if isinstance(value, (list, tuple)):
        return set().union(*[asked_vertex_maps(held) for held in value])
    return set()


def vertex_maps_lost(materials):
    """The notice for a scene read through Modo's evaluated geometry, which holds no vertex maps: a material that reads one
    has only its Low value there. Empty where no material asks for one."""
    names = sorted(asked_vertex_maps(materials))
    if not names:
        return []
    return ['The weight map %s is not read: replicators, instance overrides and masks by item, Part or Selection Set '
            'have the scene read through Modo\'s evaluated geometry, which has no vertex maps.' % ', '.join(names)]


def moonlightipr(scene):
    """What MoonLightIPR does not draw of what was read, with no notice of its own where it is packed."""
    said = []
    materials = scene.get('materials') or {}
    # Principled's sheen is MoonRay's fuzz (moonshine.sheen); a MoonRay material's own fuzz is drawn (native_surface).
    sheen = sorted(str(tag or 'the base material') for tag, material in materials.items() if isinstance(material, dict) and any(
        row.get('sheen') and not row.get('native_shader') for row in material.get('material_stack') or [material]))
    if sheen:
        said.append('MoonLightIPR does not draw the sheen of %s; it shows in MoonRay.' % ', '.join(sheen))
    limited = any(isinstance(held, dict) and (float(held.get('min_shadow_distance') or 0) > 0 or float(held.get('max_shadow_distance') or 0) > 0)
                  for held in (scene.get('production') or {}).get('lights', {}).values())
    limited = limited or any(str(entity.get('class', '')).endswith('Light') and (
        float((entity.get('parameters') or {}).get('min_shadow_distance') or 0) > 0 or float((entity.get('parameters') or {}).get('max_shadow_distance') or 0) > 0)
        for entity in scene.get('entities') or [])
    if limited:
        said.append("MoonLightIPR does not follow a light's shadow distances; they show in MoonRay.")
    # Its fog looks for light from every light (fogLight in the kernel); volumetrics links each fog to the one it is of.
    if any(isinstance(material, dict) and material.get('volume_only') for material in materials.values()):
        said.append("MoonLightIPR lights fog by every light in the scene; fog from one light's volumetrics, lit by that light alone, shows in MoonRay.")
    return said
