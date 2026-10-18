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
    from . import entities
    chosen = [item for item in scene.selected if item.type == 'camera' and entities.class_of(item) is None]
    if chosen:
        return chosen
    render = scene.renderCamera
    return [render] if render is not None and entities.class_of(render) is None else []


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
    """The Modo camera made a MoonRay camera of the chosen kind, with its lens: it takes the kind's package, and stays
    the item it is, with its name, place, parent, children, animation and links, and its part as render camera, in
    the Camera Sequence and as the dicing camera. Returns it."""
    from . import entities
    if kind not in dict(KINDS):
        raise ValueError('Unknown MoonRay camera: ' + kind)
    values = dict(entities.starting(kind), **lens(camera, kind))
    camera.PackageAdd(entities.camera_package(kind))
    for key, value in values.items():
        try:
            camera.channel(entities.CHANNEL_PREFIX + key).set(value)
        except (TypeError, ValueError, AttributeError, LookupError, RuntimeError):
            pass
    return camera
