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


def offsets(x, y, projection, aperture_x, ortho_width, pixel_aspect=1):
    if not all(math.isfinite(float(v)) for v in (x,y,aperture_x,ortho_width,pixel_aspect)) or aperture_x<=0 or pixel_aspect<=0:
        raise ValueError('Invalid camera film offset or film width')
    scale=ortho_width/aperture_x if projection=='ortho' else 1000
    # Native projection divides the complete Y window, including its offset.
    return [x*scale,y*scale*pixel_aspect]
