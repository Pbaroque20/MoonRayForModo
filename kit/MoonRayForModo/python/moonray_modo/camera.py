"""Film gate conversion shared by host capture and deferred fixtures."""
import math


def framing(width, height, aperture_x, aperture_y, pixel_aspect=1, fit='fill'):
    values=(width,height,aperture_x,aperture_y,pixel_aspect)
    if any(not math.isfinite(float(v)) or v<=0 for v in values):
        raise ValueError('Camera resolution, film gate and pixel aspect must be positive and finite')
    if fit not in ('fill','overscan','horizontal','horiz','vertical','vert'):
        raise ValueError('Unsupported camera film fit: '+str(fit))
    aspect=width*pixel_aspect/height
    if fit in ('vertical','vert') or (fit=='fill' and aspect<aperture_x/aperture_y) or (fit=='overscan' and aspect>aperture_x/aperture_y):
        aperture_x=aperture_y*aspect
    # MoonRay's projection divides vertical film extent by this value, so
    # preserve Modo's width/height ratio (the native attribute comment is stale).
    return aperture_x,pixel_aspect


def ortho_width(aperture_x, focus_distance, focal):
    """How wide, in the scene's units, an orthographic Modo camera sees: as wide as its film (as fitted, framing) seen at
    its Focus Distance through its lens, as Modo renders it (tools/probe_cl_ortho_camera.py). Its Target Distance plays
    no part: the plugin went by it, and a camera whose two distances differ came out zoomed (a report)."""
    return aperture_x * float(focus_distance) / max(1e-9, float(focal))


def offsets(x, y, projection, aperture_x, ortho_width, pixel_aspect=1):
    if not all(math.isfinite(float(v)) for v in (x,y,aperture_x,ortho_width,pixel_aspect)) or aperture_x<=0 or pixel_aspect<=0:
        raise ValueError('Invalid camera film offset or film width')
    scale=ortho_width/aperture_x if projection=='ortho' else 1000
    # Native projection divides the complete Y window, including its offset.
    return [x*scale,y*scale*pixel_aspect]


# The identity of the MoonRay spherical camera made for a Modo camera (host.spherical_camera): the Modo camera's own and this.
SPHERICAL = '|spherical'


def spherical_place(matrix, vr):
    """Where MoonRay's spherical camera made for a Modo camera stands (host.spherical_camera), the Modo camera standing at
    matrix: Spherical Map at the camera's own place; Spherical VR turned a quarter about the camera's up axis, as
    MoonRay's whole sphere has the view's direction three quarters across the picture (SphericalCamera's longitude from
    -270 to 90 degrees) and Spherical VR, seen from inside the sphere, has it in the middle, the camera's -X a quarter
    to the left. Also where a drag that moves the camera puts it (incremental.move_only)."""
    m = list(matrix)
    if not vr:
        return m
    x, y, z = m[0:3], m[4:7], m[8:11]
    return list(z) + [m[3]] + list(y) + [m[7]] + [-v for v in x] + [m[11]] + m[12:16]
