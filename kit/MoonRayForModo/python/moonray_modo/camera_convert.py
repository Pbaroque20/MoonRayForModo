"""A Modo camera made into a MoonRay camera item in its place (convert), with as much of its lens as the chosen kind has.

A perspective MoonRay camera takes the focal length, film back and offsets, pixel aspect, depth of field and bokeh, as
the plugin translates them when it renders through the Modo camera (host.snapshot); an orthographic one takes the
window's width in their place. A fisheye, spherical or dome camera takes only the place: a Modo camera has nothing
its lens could be read from. The new camera does not become the one rendered through: that is chosen in Render
Settings, Camera, as before."""
import math

# (MoonRay class, what the popup says).
KINDS = (('PerspectiveCamera', 'Perspective'), ('OrthographicCamera', 'Orthographic'), ('FisheyeCamera', 'Fisheye'),
         ('SphericalCamera', 'Spherical'), ('DomeMaster3DCamera', 'Dome (DomeMaster3D)'))


def selected_cameras():
    """The Modo cameras selected, or the render camera where none is."""
    import modo
    scene = modo.Scene()
    chosen = [item for item in scene.selected if item.type == 'camera']
    return chosen or ([scene.renderCamera] if scene.renderCamera is not None else [])


def suited(camera):
    """The kind a Modo camera is most like: orthographic for an orthographic one, otherwise perspective."""
    from .host import channel
    return 'OrthographicCamera' if channel(camera, 'projType', 'persp') == 'ortho' else 'PerspectiveCamera'


def lens(camera, kind):
    """The MoonRay attributes the chosen kind takes from the Modo camera, as host.snapshot reads them."""
    import modo
    from . import properties
    from .camera import framing, offsets
    from .host import channel
    if kind not in ('PerspectiveCamera', 'OrthographicCamera'):
        return {}
    render = modo.Scene().renderItem
    width, height = int(channel(render, 'resX', 1280)), int(channel(render, 'resY', 720))
    pixel_aspect = float(channel(render, 'pAspect', 1))
    if channel(camera, 'resOverride', 0):
        width, height = int(channel(camera, 'resX', width)), int(channel(camera, 'resY', height))
        pixel_aspect = float(channel(camera, 'pAspect', pixel_aspect))
    # The offset is measured as the camera being made measures it: across the film, or across the window.
    projection = 'ortho' if kind == 'OrthographicCamera' else 'persp'
    aperture_x, moonray_pixel_aspect = framing(width, height, float(channel(camera, 'apertureX', .036)),
                                               float(channel(camera, 'apertureY', .024)), pixel_aspect, channel(camera, 'filmFit', 'fill'))
    focal = float(channel(camera, 'focalLen', .05))
    ortho_width = float(properties.read(camera).get('ortho_width', aperture_x * float(channel(camera, 'target', 1)) / max(1e-9, focal)))
    film_offset = offsets(float(channel(camera, 'offsetX', 0)), float(channel(camera, 'offsetY', 0)), projection, aperture_x,
                          ortho_width, pixel_aspect)
    blades = int(channel(camera, 'irisBlades', 0))
    result = {'horizontal_film_offset': film_offset[0], 'vertical_film_offset': film_offset[1],
              'pixel_aspect_ratio': moonray_pixel_aspect, 'dof': bool(channel(camera, 'dof', 0)),
              'dof_aperture': float(channel(camera, 'fStop', 4)), 'dof_focus_distance': float(channel(camera, 'focusDist', 4)),
              'bokeh': blades >= 3, 'bokeh_sides': max(0, blades), 'bokeh_angle': math.degrees(float(channel(camera, 'irisRot', 0)))}
    if kind == 'PerspectiveCamera':
        result.update(focal=focal * 1000, film_width_aperture=aperture_x * 1000)
    else:
        result.update(film_width_aperture=ortho_width)
    return result


def place(item, matrix):
    """Puts an item where a world matrix says, with no parent: position, a turn and a scale along its axes."""
    import modo
    from .rdl_import import decomposed
    parts = decomposed(matrix)
    if parts is None:
        raise ValueError('The camera shears or mirrors, which a MoonRay camera item cannot copy')
    position, turn, sizes = parts
    locator = item if hasattr(item, 'position') else modo.LocatorSuperType(item)
    locator.position.set(position)
    locator.rotation.set(modo.Matrix4([row + [0.0] for row in turn] + [[0.0, 0.0, 0.0, 1.0]]).asEuler())
    locator.scale.set(sizes)


def retarget(old, new):
    """The scene's MoonRay settings that name a camera by its identity, the Camera Sequence's keys and the dicing
    camera, made to name the camera that replaced it."""
    import modo
    from . import properties
    if old == new:
        return
    stored = properties.scene_settings()
    changed = False
    sequence = stored.get('camera_sequence')
    if isinstance(sequence, dict):
        for key in sequence.get('keys') or []:
            if isinstance(key, dict) and key.get('camera') == old:
                key['camera'] = new
                changed = True
    if stored.get('dicing_camera') == old:
        stored['dicing_camera'] = new
        changed = True
    if changed:
        properties.write(modo.Scene().renderItem, stored)


def convert(camera, kind):
    """The Modo camera made a MoonRay camera of the chosen kind, with its lens, in its place: the Modo camera is gone.

    Modo's Change Type makes the camera the new kind as it stands, MoonRay's cameras being Modo cameras too, so that
    its name, place, parent, children, animation and links, and being the render camera, are kept. Where Modo will
    not change it, a new camera is made where it stands and given its name, children and render camera, and the Modo
    camera is deleted; its animation is then not carried over. Either way, the Camera Sequence's keys and the dicing
    camera that named it name the new one. Returns the MoonRay camera."""
    import lx
    import modo
    from . import entities
    from .host import world_matrix
    if kind not in dict(KINDS):
        raise ValueError('Unknown MoonRay camera: ' + kind)
    scene = modo.Scene()
    values = dict(entities.starting(kind), **lens(camera, kind))
    old, name, wanted = camera.id, camera.name, entities.item_type(kind)
    render = scene.renderCamera is not None and scene.renderCamera.id == old
    item = None
    try:
        lx.eval('select.item {%s} set' % old)
        lx.eval('item.setType {%s}' % wanted)
        made = [i for i in modo.Scene().selected if i.type == wanted]
        item = made[-1] if made else None
    except Exception:
        item = None
    if item is None:
        children = list(camera.children())
        item = scene.addItem(wanted, name=name)
        place(item, world_matrix(camera))
        for child in children:
            lx.eval('item.parent {%s} {%s} 0 inPlace:1' % (child.id, item.id))
        scene.removeItems(camera)
        item.name = name
        lx.out('MoonRay: %s was made a new MoonRay camera in its place; its animation, if it had any, was not carried over.' % name)
    for key, value in values.items():
        try:
            item.channel(entities.CHANNEL_PREFIX + key).set(value)
        except (TypeError, ValueError, AttributeError, LookupError, RuntimeError):
            pass
    if render:
        # Modo's Change Type leaves the scene with another render camera.
        lx.eval('render.camera {%s}' % item.id)
    retarget(old, item.id)
    return item
