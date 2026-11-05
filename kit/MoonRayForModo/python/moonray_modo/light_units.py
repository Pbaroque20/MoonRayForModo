"""Modo's light strength in MoonRay's terms.

Modo's radiance and MoonRay's intensity measure different things, differently for each kind of
light, so a Modo light given to MoonRay unchanged comes out wrong by a different amount each
time. These factors are measured, not derived: tools/probe_light_units.py lights a white card
with each kind in Modo, and tools/check_light_units.py renders the same in MoonRay.

    Directional  Modo: what falls on a surface facing it.   MoonRay: what a white surface then shows.
    Point        Modo: per steradian.                       MoonRay: the light's whole output.
    Spot         Modo: per steradian.                       MoonRay: of a disc, a quarter of the point's on its axis.
    Area         Modo: per square metre of the light.       MoonRay: the light's whole output.
    Mesh         Modo: per square metre, as Area.            MoonRay: the light's whole output (by Area's rule, not measured).
"""
import math


def intensity(kind, radiance, light, shape='rectangle'):
    """The MoonRay intensity that lights a scene as a Modo light of this radiance does."""
    if kind == 'sunLight':
        return radiance / math.pi
    if kind == 'pointLight':
        return radiance * 4 * math.pi
    if kind == 'spotLight':
        # On its axis. MoonRay's spot is a small disc and dims by the cosine of the angle off the axis,
        # which Modo's does not: a quarter dimmer at the edge of an 80 degree cone.
        return radiance * math.pi
    if kind == 'meshLight':
        # Per square metre, as an area light: MoonRay's MeshLight, normalized, spreads its intensity over the mesh's area.
        return radiance * math.pi * float(light.get('area', 1))
    if kind == 'areaLight':
        area = float(light.get('width', 1)) * float(light.get('height', 1))
        # An ellipse fills pi/4 of its rectangle.
        return radiance * math.pi * area * (math.pi / 4 if shape == 'ellipse' else 1.0)
    return radiance
