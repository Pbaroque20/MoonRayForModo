"""A Modo area light made into a MoonRay RectLight item in its place (convert), lighting the scene as it did.

Modo's Change Type (item.setType) makes it the MoonRay item: it keeps its name, place, parent, children, animation of
its place, and its Lighting controls. Its size, colour and strength are given to the RectLight as the plugin translates
the area light when it renders it (host.snapshot, light_units): Modo's radiance is per square metre of the light,
MoonRay's intensity the whole light's. An ellipse-shaped area light is not converted: a RectLight is a rectangle."""
import math

KIND = 'RectLight'


def selected_area_lights():
    """The Modo area lights selected."""
    import modo
    return [item for item in modo.Scene().selected if item.type == 'areaLight']


def values(light):
    """What the RectLight is given, by MoonRay attribute: its size, colour, intensity, and whether the camera sees it."""
    from .host import channel, color
    from .light_units import intensity
    material = next((child for child in light.children() if child.type == 'lightMaterial'), None)
    width, height = float(channel(light, 'width', 1)), float(channel(light, 'height', 1))
    held = {'width': width, 'height': height,
            'intensity': intensity('areaLight', float(channel(light, 'radiance', 1)), {'width': width, 'height': height}, 'rectangle'),
            'color': list(color(material, 'lightCol')) if material is not None else [1.0, 1.0, 1.0]}
    if channel(light, 'visCam', 0):
        # Seen where it stands, as Modo's Visible to Camera shows it (MoonRay's visible_in_camera, 1: on).
        held['visible_in_camera'] = 1
    return held


def convertible(light):
    """Why a light cannot be converted, or None."""
    from .host import channel
    if light.type != 'areaLight':
        return '%s is not an area light' % light.name
    if str(channel(light, 'shape', 'rectangle')) == 'ellipse':
        return '%s is an ellipse; a MoonRay RectLight is a rectangle' % light.name
    return None


def retarget(old, new):
    """The scene's Lighting controls kept for the light (by its identity) given to the item that replaced it."""
    import modo
    from . import properties
    if old == new:
        return
    stored = properties.scene_settings()
    lights = (stored.get('production') or {}).get('lights') or {}
    if old in lights and new not in lights:
        lights[new] = lights.pop(old)
        properties.write(modo.Scene().renderItem, stored)


def apply(item, held):
    """The RectLight's channels set to held (values()). Returns the attributes that could not be set."""
    from . import entities
    failed = []
    for key, value in held.items():
        try:
            if isinstance(value, (list, tuple)):
                for suffix, part in zip(('.R', '.G', '.B'), value):
                    item.channel(entities.CHANNEL_PREFIX + key + suffix).set(float(part))
            else:
                item.channel(entities.CHANNEL_PREFIX + key).set(value)
        except (TypeError, ValueError, AttributeError, LookupError, RuntimeError):
            failed.append(key)
    return failed


def convert(light):
    """The area light made a MoonRay RectLight (call inside a command). Returns (the new item, the attributes it could
    not be given)."""
    import lx
    import modo
    from . import entities
    reason = convertible(light)
    if reason:
        raise ValueError(reason)
    held = values(light)
    old = light.id
    material = next((child for child in light.children() if child.type == 'lightMaterial'), None)
    lx.eval('select.item {%s} set' % old)
    lx.eval('item.setType {%s}' % entities.item_type(KIND))
    made = [item for item in modo.Scene().selected if item.type == entities.item_type(KIND)]
    if not made:
        raise ValueError('%s could not be made a MoonRay RectLight' % light.name)
    item = made[-1]
    failed = apply(item, held)
    retarget(old, item.id)
    # The Modo light's own light material is the area light's, not the RectLight's: its colour is in the RectLight now.
    if material is not None:
        try:
            if material.parent is not None and material.parent.id == item.id:
                modo.Scene().removeItems(material)
        except (LookupError, RuntimeError, AttributeError):
            pass
    return item, failed
