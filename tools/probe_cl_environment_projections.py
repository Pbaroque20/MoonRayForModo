# python
"""Command-line test: an environment image under each of Modo's Texture Locator projections, as Modo renders it and as
the plugin writes it for MoonRay. The image is tools/make_uv_code_image.py's (its colour is where in it a pixel is), so
Modo's render, through a spherical camera at the origin (the whole sphere, latitude-longitude), reads as the image
coordinate Modo looks up for each direction. Each case renders Modo's picture (modo_<case>.exr) and writes the plugin's
scene for MoonRay (<case>.rdla, rendering moonray_<case>.exr) with what the plugin warned. Also an Ocean Plane-free
procedural (Grid) case. Writes report.json beside them; tools/check_environment_projections.py renders and compares.

PROBE_OUT is the folder (test-results/env-projections by default); PROBE_IMAGE the image (uv_code.exr in it);
PROBE_CASES a comma-separated list of case names to render (all by default)."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\env-projections'))
out.mkdir(parents=True, exist_ok=True)
IMAGE = os.environ.get('PROBE_IMAGE', str(out / 'uv_code.exr'))
ONLY = [c for c in os.environ.get('PROBE_CASES', '').split(',') if c]
SIZE = (360, 180)
# PROBE_RES=WxH: a larger picture (the thin-line procedural cases are read at 1440 x 720).
if os.environ.get('PROBE_RES'):
    SIZE = tuple(int(v) for v in os.environ['PROBE_RES'].lower().split('x'))
# PROBE_SWITCH=off: the plugin's scenes written with the Source Override off (native.environment_projections), named
# <case>_off; Modo's own picture is not rendered again.
OFF = os.environ.get('PROBE_SWITCH', 'on') == 'off'
# PROBE_VIEWS=cube: each case seen by a 90-degree perspective camera in the six directions of a cube's faces
# (<name>_v0 .. _v5: -Z, -X, +Z, +X, up, down) into the views folder, as the comparison pictures are made (the spherical
# camera's pictures read the projections' arithmetic; a renderer's own spherical camera is not what is compared).
CUBE = os.environ.get('PROBE_VIEWS') == 'cube'
VIEWS = ((0, 0, 0), (0, 90, 0), (0, 180, 0), (0, 270, 0), (90, 0, 0), (-90, 0, 0))
if CUBE:
    SIZE = (160, 160)
    out = out / 'views'
    out.mkdir(parents=True, exist_ok=True)
TAG = '_off' if OFF else ''
result = {'cases': {}}
if (ONLY or OFF) and (out / 'report.json').is_file():
    # Only some cases again: the others' entries kept.
    result = json.loads((out / 'report.json').read_text())
    result.pop('error', None)

# name: (projType, axis, locator rotation degrees XYZ, locator size XYZ, extra locator channels, layer kind)
CASES = [
    ('spherical', 'spherical', 1, (0, 0, 0), (1, 1, 1), {}, 'image'),
    ('planar_x', 'planar', 0, (0, 0, 0), (1, 1, 1), {}, 'image'),
    ('planar_y', 'planar', 1, (0, 0, 0), (1, 1, 1), {}, 'image'),
    ('planar_z', 'planar', 2, (0, 0, 0), (1, 1, 1), {}, 'image'),
    ('cylindrical_x', 'cylindrical', 0, (0, 0, 0), (1, 1, 1), {}, 'image'),
    ('cylindrical_y', 'cylindrical', 1, (0, 0, 0), (1, 1, 1), {}, 'image'),
    ('cylindrical_z', 'cylindrical', 2, (0, 0, 0), (1, 1, 1), {}, 'image'),
    ('spherical_x', 'spherical', 0, (0, 0, 0), (1, 1, 1), {}, 'image'),
    ('spherical_z', 'spherical', 2, (0, 0, 0), (1, 1, 1), {}, 'image'),
    ('cubic', 'cubic', 1, (0, 0, 0), (1, 1, 1), {}, 'image'),
    ('box', 'box', 1, (0, 0, 0), (1, 1, 1), {}, 'image'),
    ('front', 'front', 1, (0, 0, 0), (1, 1, 1), {}, 'image'),
    ('uv', 'uv', 1, (0, 0, 0), (1, 1, 1), {}, 'image'),
    ('lightprobe', 'lightprobe', 1, (0, 0, 0), (1, 1, 1), {}, 'image'),
    ('lightprobe_x', 'lightprobe', 0, (0, 0, 0), (1, 1, 1), {}, 'image'),
    ('lightprobe_z', 'lightprobe', 2, (0, 0, 0), (1, 1, 1), {}, 'image'),
    ('implicit', 'implicitUV', 1, (0, 0, 0), (1, 1, 1), {}, 'image'),
    ('triplanar', 'triplanar', 1, (0, 0, 0), (1, 1, 1), {}, 'image'),
    ('solid', 'none', 1, (0, 0, 0), (1, 1, 1), {}, 'image'),
    # Placed: turned, sized and its UVs moved.
    ('planar_y_placed', 'planar', 1, (20, 35, 10), (2, .5, 1.5), {'wrapU': 2.0, 'uvRotation': 30.0}, 'image'),
    ('cylindrical_y_placed', 'cylindrical', 1, (20, 35, 10), (2, .5, 1.5), {'wrapU': 2.0, 'uvRotation': 30.0}, 'image'),
    ('spherical_placed', 'spherical', 1, (20, 35, 10), (2, .5, 1.5), {'wrapU': 2.0, 'uvRotation': 30.0}, 'image'),
    ('cubic_placed', 'cubic', 1, (20, 35, 10), (2, .5, 1.5), {'wrapU': 2.0, 'uvRotation': 30.0}, 'image'),
    ('box_placed', 'box', 1, (20, 35, 10), (2, .5, 1.5), {'wrapU': 2.0, 'uvRotation': 30.0}, 'image'),
    ('lightprobe_placed', 'lightprobe', 1, (20, 35, 10), (2, .5, 1.5), {'wrapU': 2.0, 'uvRotation': 30.0}, 'image'),
    ('front_placed', 'front', 1, (20, 35, 10), (2, .5, 1.5), {'wrapU': 2.0, 'uvRotation': 30.0}, 'image'),
    ('planar_z_sized', 'planar', 2, (0, 0, 0), (3, 3, 3), {}, 'image'),
    ('planar_z_moved', 'planar', 2, (0, 0, 0), (1, 1, 1), {'pos': (2.0, 1.0, -3.0)}, 'image'),
    # Procedurals.
    ('grid_planar_y', 'planar', 1, (0, 0, 0), (.5, .5, .5), {}, 'grid'),
    ('grid_cubic', 'cubic', 1, (0, 0, 0), (.5, .5, .5), {}, 'grid'),
    ('grid_cylindrical_y', 'cylindrical', 1, (0, 0, 0), (.5, .5, .5), {}, 'grid'),
    ('grid_spherical', 'spherical', 1, (0, 0, 0), (.5, .5, .5), {}, 'grid'),
    # One placement at a time.
    ('spherical_rot', 'spherical', 1, (20, 35, 10), (1, 1, 1), {}, 'image'),
    ('planar_y_rot', 'planar', 1, (20, 35, 10), (1, 1, 1), {}, 'image'),
    ('cubic_rot', 'cubic', 1, (20, 35, 10), (1, 1, 1), {}, 'image'),
    ('planar_y_size', 'planar', 1, (0, 0, 0), (2, .5, 1.5), {}, 'image'),
    ('planar_y_rotsize', 'planar', 1, (20, 35, 10), (2, .5, 1.5), {}, 'image'),
    ('planar_y_wrap', 'planar', 1, (0, 0, 0), (1, 1, 1), {'wrapU': 2.0, 'wrapV': 3.0}, 'image'),
    ('planar_y_uvrot', 'planar', 1, (0, 0, 0), (1, 1, 1), {'uvRotation': 30.0}, 'image'),
    ('planar_y_offset', 'planar', 1, (0, 0, 0), (1, 1, 1), {'m02': .25, 'm12': .1}, 'image'),
    ('spherical_wrap', 'spherical', 1, (0, 0, 0), (1, 1, 1), {'wrapU': 2.0, 'wrapV': 3.0}, 'image'),
    ('spherical_uvrot', 'spherical', 1, (0, 0, 0), (1, 1, 1), {'uvRotation': 30.0}, 'image'),
    ('planar_y_reset', 'planar', 1, (0, 0, 0), (.6, .6, .6), {'tileU': 'reset', 'tileV': 'reset'}, 'image'),
    ('planar_y_mirror', 'planar', 1, (0, 0, 0), (.6, .6, .6), {'tileU': 'mirror', 'tileV': 'edge'}, 'image'),
    ('cubic_x', 'cubic', 0, (0, 0, 0), (1, 1, 1), {}, 'image'),
    ('box_x', 'box', 0, (0, 0, 0), (1, 1, 1), {}, 'image'),
    ('triplanar_x', 'triplanar', 0, (0, 0, 0), (1, 1, 1), {}, 'image'),
    ('triplanar_h2', 'triplanar', 1, (0, 0, 0), (1, 1, 1), {'triplanarBlending': .2}, 'image'),
    ('triplanar_h8', 'triplanar', 1, (0, 0, 0), (1, 1, 1), {'triplanarBlending': .8}, 'image'),
    ('uv_sq', 'uv', 1, (0, 0, 0), (1, 1, 1), {'image': 'uv_sq'}, 'image'),
    ('implicit_sq', 'implicitUV', 1, (0, 0, 0), (1, 1, 1), {'image': 'uv_sq'}, 'image'),
    ('solid_sq', 'none', 1, (0, 0, 0), (1, 1, 1), {'image': 'uv_sq'}, 'image'),
    ('front_persp', 'front', 1, (0, 0, 0), (1, 1, 1), {'camera': 'persp'}, 'image'),
    ('front_persp_placed', 'front', 1, (20, 35, 10), (2, .5, 1.5), {'camera': 'persp', 'wrapU': 2.0}, 'image'),
    ('planar_z_persp', 'planar', 2, (0, 0, 0), (3, 3, 3), {'camera': 'persp'}, 'image'),
    ('spherical_persp', 'spherical', 1, (0, 0, 0), (1, 1, 1), {'camera': 'persp'}, 'image'),
    ('spherical_rot_persp', 'spherical', 1, (20, 35, 10), (1, 1, 1), {'camera': 'persp'}, 'image'),
    ('spherical_rot_persp_side', 'spherical', 1, (20, 35, 10), (1, 1, 1), {'camera': 'persp', 'view': (0, 90, 0)}, 'image'),
    ('spherical_layered_persp', 'spherical', 1, (0, 0, 0), (1, 1, 1), {'camera': 'persp', 'opacity': .999}, 'image'),
    ('spherical_layered_persp_side', 'spherical', 1, (20, 35, 10), (1, 1, 1), {'camera': 'persp', 'opacity': .999, 'view': (0, 90, 0)}, 'image'),
    ('planar_x_persp_side', 'planar', 0, (20, 35, 10), (3, 3, 3), {'camera': 'persp', 'view': (0, 90, 0)}, 'image'),
    ('cylindrical_uvrot1', 'cylindrical', 1, (0, 0, 0), (1, 1, 1), {'uvRotation': 30.0}, 'image'),
    ('cylindrical_wrap1', 'cylindrical', 1, (0, 0, 0), (1, 1, 1), {'wrapU': 2.0, 'wrapV': 3.0}, 'image'),
    ('cylindrical_size1', 'cylindrical', 1, (0, 0, 0), (2, .5, 1.5), {}, 'image'),
    ('cylindrical_rot1', 'cylindrical', 1, (20, 35, 10), (1, 1, 1), {}, 'image'),
    ('cylindrical_wraprot1', 'cylindrical', 1, (0, 0, 0), (1, 1, 1), {'wrapU': 2.0, 'wrapV': 3.0, 'uvRotation': 30.0}, 'image'),
    ('spherical_uvrot1', 'spherical', 1, (0, 0, 0), (1, 1, 1), {'uvRotation': 30.0}, 'image'),
    ('spherical_wrap1', 'spherical', 1, (0, 0, 0), (1, 1, 1), {'wrapU': 2.0, 'wrapV': 3.0}, 'image'),
    ('spherical_size1', 'spherical', 1, (0, 0, 0), (2, .5, 1.5), {}, 'image'),
    ('spherical_rot1', 'spherical', 1, (20, 35, 10), (1, 1, 1), {}, 'image'),
    ('spherical_wraprot1', 'spherical', 1, (0, 0, 0), (1, 1, 1), {'wrapU': 2.0, 'wrapV': 3.0, 'uvRotation': 30.0}, 'image'),
    ('box_uvrot1', 'box', 1, (0, 0, 0), (1, 1, 1), {'uvRotation': 30.0}, 'image'),
    ('box_wrap1', 'box', 1, (0, 0, 0), (1, 1, 1), {'wrapU': 2.0, 'wrapV': 3.0}, 'image'),
    ('box_size1', 'box', 1, (0, 0, 0), (2, .5, 1.5), {}, 'image'),
    ('box_rot1', 'box', 1, (20, 35, 10), (1, 1, 1), {}, 'image'),
    ('box_wraprot1', 'box', 1, (0, 0, 0), (1, 1, 1), {'wrapU': 2.0, 'wrapV': 3.0, 'uvRotation': 30.0}, 'image'),
    ('lightprobe_uvrot1', 'lightprobe', 1, (0, 0, 0), (1, 1, 1), {'uvRotation': 30.0}, 'image'),
    ('lightprobe_wrap1', 'lightprobe', 1, (0, 0, 0), (1, 1, 1), {'wrapU': 2.0, 'wrapV': 3.0}, 'image'),
    ('lightprobe_size1', 'lightprobe', 1, (0, 0, 0), (2, .5, 1.5), {}, 'image'),
    ('lightprobe_rot1', 'lightprobe', 1, (20, 35, 10), (1, 1, 1), {}, 'image'),
    ('lightprobe_wraprot1', 'lightprobe', 1, (0, 0, 0), (1, 1, 1), {'wrapU': 2.0, 'wrapV': 3.0, 'uvRotation': 30.0}, 'image'),
    ('cubic_uvrot1', 'cubic', 1, (0, 0, 0), (1, 1, 1), {'uvRotation': 30.0}, 'image'),
    ('cubic_wrap1', 'cubic', 1, (0, 0, 0), (1, 1, 1), {'wrapU': 2.0, 'wrapV': 3.0}, 'image'),
    ('cubic_size1', 'cubic', 1, (0, 0, 0), (2, .5, 1.5), {}, 'image'),
    ('cubic_rot1', 'cubic', 1, (20, 35, 10), (1, 1, 1), {}, 'image'),
    ('cubic_wraprot1', 'cubic', 1, (0, 0, 0), (1, 1, 1), {'wrapU': 2.0, 'wrapV': 3.0, 'uvRotation': 30.0}, 'image'),
    # Light Probe on a locator both turned and sized unevenly (Modo takes the turn from the locator's columns).
    ('lightprobe_rotsize', 'lightprobe', 1, (20, 35, 10), (2, .5, 1.5), {}, 'image'),
    ('lightprobe_rotsize_x', 'lightprobe', 0, (-30, 10, 50), (.4, 1.5, 3), {}, 'image'),
    # Procedurals: each of the Grid's and Dots' types the plugin lays, a planar locator a quarter unit across (many
    # cells), wide soft lines to read their profile; then the placements one by one (extra 'layer': the layer's channels).
    ('proc_grid_square', 'planar', 1, (0, 0, 0), (.25, .25, .25), {'layer': {'type': 'square', 'lineWidth': .2, 'transWidth': .3}}, 'grid'),
    ('proc_grid_line', 'planar', 1, (0, 0, 0), (.25, .25, .25), {'layer': {'type': 'line', 'lineWidth': .2, 'transWidth': .3}}, 'grid'),
    ('proc_grid_triangle', 'planar', 1, (0, 0, 0), (.25, .25, .25), {'layer': {'type': 'triangle', 'lineWidth': .2, 'transWidth': .3}}, 'grid'),
    ('proc_grid_hexagon', 'planar', 1, (0, 0, 0), (.25, .25, .25), {'layer': {'type': 'hexagon', 'lineWidth': .2, 'transWidth': .3}}, 'grid'),
    ('proc_grid_hard', 'planar', 1, (0, 0, 0), (.25, .25, .25), {'layer': {'type': 'square', 'lineWidth': .3, 'transWidth': 0.0}}, 'grid'),
    ('proc_grid_biasgain', 'planar', 1, (0, 0, 0), (.25, .25, .25), {'layer': {'type': 'square', 'lineWidth': .2, 'transWidth': .5, 'bias': .3, 'gain': .7}}, 'grid'),
    ('proc_dots_square', 'planar', 1, (0, 0, 0), (.25, .25, .25), {'layer': {'type': 'square', 'dotWidth': .6, 'transWidth': .3}}, 'dots'),
    ('proc_dots_hexagon', 'planar', 1, (0, 0, 0), (.25, .25, .25), {'layer': {'type': 'hexagon', 'dotWidth': .6, 'transWidth': .3}}, 'dots'),
    ('proc_dots_wide', 'planar', 1, (0, 0, 0), (.25, .25, .25), {'layer': {'type': 'square', 'dotWidth': .9, 'transWidth': .6}}, 'dots'),
    ('proc_planar_z', 'planar', 2, (0, 0, 0), (.25, .25, .25), {'layer': {'type': 'square', 'lineWidth': .2, 'transWidth': .3}}, 'grid'),
    ('proc_planar_placed', 'planar', 1, (20, 35, 10), (.5, .25, .4), {'wrapU': 2.0, 'wrapV': 3.0, 'uvRotation': 30.0,
                                                                        'layer': {'type': 'square', 'lineWidth': .2, 'transWidth': .3}}, 'grid'),
    ('proc_planar_uvrot', 'planar', 1, (0, 0, 0), (.25, .25, .25), {'uvRotation': 30.0, 'layer': {'type': 'square', 'lineWidth': .2, 'transWidth': .3}}, 'grid'),
    ('proc_planar_wrap', 'planar', 1, (0, 0, 0), (.25, .25, .25), {'wrapU': 2.0, 'wrapV': 3.0, 'layer': {'type': 'square', 'lineWidth': .2, 'transWidth': .3}}, 'grid'),
    ('proc_planar_reset', 'planar', 1, (0, 0, 0), (.6, .6, .6), {'tileU': 'reset', 'tileV': 'mirror', 'layer': {'type': 'square', 'lineWidth': .2, 'transWidth': .3}}, 'grid'),
    ('proc_spherical', 'spherical', 1, (0, 0, 0), (1, 1, 1), {'layer': {'type': 'square', 'lineWidth': .1, 'transWidth': .1}}, 'grid'),
    ('proc_spherical_wrap', 'spherical', 1, (0, 0, 0), (1, 1, 1), {'wrapU': 4.0, 'wrapV': 3.0, 'layer': {'type': 'square', 'lineWidth': .1, 'transWidth': .1}}, 'grid'),
    ('proc_spherical_placed', 'spherical', 1, (20, 35, 10), (2, .5, 1.5), {'wrapU': 4.0, 'wrapV': 3.0, 'uvRotation': 30.0,
                                                                            'layer': {'type': 'square', 'lineWidth': .1, 'transWidth': .1}}, 'grid'),
    ('proc_spherical_x', 'spherical', 0, (0, 0, 0), (1, 1, 1), {'wrapU': 4.0, 'wrapV': 3.0, 'layer': {'type': 'hexagon', 'lineWidth': .1, 'transWidth': .1}}, 'grid'),
    ('proc_cylindrical_z', 'cylindrical', 2, (0, 0, 0), (.5, .5, .5), {'wrapU': 4.0, 'layer': {'type': 'square', 'lineWidth': .1, 'transWidth': .1}}, 'grid'),
    ('proc_cylindrical_placed', 'cylindrical', 1, (20, 35, 10), (.5, .25, .4), {'wrapU': 4.0, 'wrapV': 2.0, 'uvRotation': 30.0,
                                                                                 'layer': {'type': 'square', 'lineWidth': .1, 'transWidth': .1}}, 'grid'),
    ('proc_cubic_placed', 'cubic', 1, (20, 35, 10), (.5, .25, .4), {'uvRotation': 30.0, 'layer': {'type': 'square', 'dotWidth': .6, 'transWidth': .3}}, 'dots'),
    ('proc_box', 'box', 1, (0, 0, 0), (.25, .5, .5), {'layer': {'type': 'square', 'lineWidth': .2, 'transWidth': .3}}, 'grid'),
    ('proc_lightprobe', 'lightprobe', 1, (20, 35, 10), (2, .5, 1.5), {'layer': {'type': 'square', 'lineWidth': .1, 'transWidth': .1}}, 'grid'),
    ('proc_triplanar', 'triplanar', 1, (0, 0, 0), (.25, .25, .25), {'triplanarBlending': .3, 'layer': {'type': 'square', 'lineWidth': .2, 'transWidth': .3}}, 'grid'),
    ('proc_uv', 'uv', 1, (0, 0, 0), (.25, .25, .25), {'layer': {'type': 'square', 'lineWidth': .2, 'transWidth': .3}}, 'grid'),
    ('proc_uv_placed', 'uv', 1, (20, 35, 10), (.5, .25, .4), {'wrapU': 2.0, 'uvRotation': 30.0, 'layer': {'type': 'square', 'lineWidth': .2, 'transWidth': .3}}, 'grid'),
    ('proc_front', 'front', 1, (0, 0, 0), (.25, .25, .25), {'layer': {'type': 'square', 'lineWidth': .2, 'transWidth': .3}}, 'grid'),
    ('proc_implicit', 'implicitUV', 1, (0, 0, 0), (.25, .25, .25), {'layer': {'type': 'square', 'lineWidth': .2, 'transWidth': .3}}, 'grid'),
    ('proc_triplanar_hard', 'triplanar', 1, (0, 0, 0), (.25, .25, .25), {'triplanarBlending': 1.0, 'layer': {'type': 'square', 'lineWidth': .1, 'transWidth': 0.0}}, 'grid'),
    ('proc_triplanar_soft', 'triplanar', 1, (0, 0, 0), (.5, .5, .5), {'triplanarBlending': 0.0, 'layer': {'type': 'line', 'lineWidth': .1, 'transWidth': .1}}, 'grid'),
    # Triplanar procedurals, to read Modo's rule for them: the shapes that are not symmetric (Triangle, Hexagon, Dots),
    # hardness, uneven sizes, a turn, the axis, UV Rotation and the Wraps one by one.
    ('tri_dots_square', 'triplanar', 1, (0, 0, 0), (.25, .25, .25), {'triplanarBlending': .5, 'layer': {'type': 'square', 'dotWidth': .4, 'transWidth': .2}}, 'dots'),
    ('tri_dots_hexagon', 'triplanar', 1, (0, 0, 0), (.25, .25, .25), {'triplanarBlending': .5, 'layer': {'type': 'hexagon', 'dotWidth': .4, 'transWidth': .2}}, 'dots'),
    ('tri_grid_triangle', 'triplanar', 1, (0, 0, 0), (.25, .25, .25), {'triplanarBlending': .5, 'layer': {'type': 'triangle', 'lineWidth': .1, 'transWidth': .1}}, 'grid'),
    ('tri_grid_hexagon', 'triplanar', 1, (0, 0, 0), (.25, .25, .25), {'triplanarBlending': .5, 'layer': {'type': 'hexagon', 'lineWidth': .1, 'transWidth': .1}}, 'grid'),
    ('tri_hard_h1', 'triplanar', 1, (0, 0, 0), (.25, .25, .25), {'triplanarBlending': .1, 'layer': {'type': 'square', 'lineWidth': .2, 'transWidth': .3}}, 'grid'),
    ('tri_hard_h6', 'triplanar', 1, (0, 0, 0), (.25, .25, .25), {'triplanarBlending': .6, 'layer': {'type': 'square', 'lineWidth': .2, 'transWidth': .3}}, 'grid'),
    ('tri_size', 'triplanar', 1, (0, 0, 0), (.2, .35, .5), {'triplanarBlending': .5, 'layer': {'type': 'square', 'lineWidth': .2, 'transWidth': .3}}, 'grid'),
    ('tri_rot', 'triplanar', 1, (20, 35, 10), (.25, .25, .25), {'triplanarBlending': .5, 'layer': {'type': 'square', 'lineWidth': .2, 'transWidth': .3}}, 'grid'),
    ('tri_rotsize', 'triplanar', 1, (20, 35, 10), (.2, .35, .5), {'triplanarBlending': .5, 'layer': {'type': 'triangle', 'lineWidth': .1, 'transWidth': .1}}, 'grid'),
    ('tri_axis_x', 'triplanar', 0, (0, 0, 0), (.25, .25, .25), {'triplanarBlending': .5, 'layer': {'type': 'triangle', 'lineWidth': .1, 'transWidth': .1}}, 'grid'),
    ('tri_axis_z', 'triplanar', 2, (0, 0, 0), (.25, .25, .25), {'triplanarBlending': .5, 'layer': {'type': 'triangle', 'lineWidth': .1, 'transWidth': .1}}, 'grid'),
    ('tri_uvrot', 'triplanar', 1, (0, 0, 0), (.25, .25, .25), {'triplanarBlending': .5, 'uvRotation': 30.0, 'layer': {'type': 'square', 'lineWidth': .2, 'transWidth': .3}}, 'grid'),
    ('tri_wrap', 'triplanar', 1, (0, 0, 0), (.25, .25, .25), {'triplanarBlending': .5, 'wrapU': 2.0, 'wrapV': 3.0, 'layer': {'type': 'square', 'lineWidth': .2, 'transWidth': .3}}, 'grid'),
    ('tri_line', 'triplanar', 1, (0, 0, 0), (.25, .25, .25), {'triplanarBlending': .5, 'uvRotation': 90.0, 'layer': {'type': 'line', 'lineWidth': .1, 'transWidth': .1}}, 'grid'),
    # Thin hard lines and dots, half a unit across, to read the shapes of the lattices (PROBE_RES=1440x720).
    ('thin_grid_triangle', 'planar', 1, (0, 0, 0), (.5, .5, .5), {'layer': {'type': 'triangle', 'lineWidth': .04, 'transWidth': 0.0}}, 'grid'),
    ('thin_grid_hexagon', 'planar', 1, (0, 0, 0), (.5, .5, .5), {'layer': {'type': 'hexagon', 'lineWidth': .04, 'transWidth': 0.0}}, 'grid'),
    ('thin_grid_square', 'planar', 1, (0, 0, 0), (.5, .5, .5), {'layer': {'type': 'square', 'lineWidth': .04, 'transWidth': 0.0}}, 'grid'),
    ('thin_dots_hexagon', 'planar', 1, (0, 0, 0), (.5, .5, .5), {'layer': {'type': 'hexagon', 'dotWidth': .3, 'transWidth': 0.0}}, 'dots'),
    ('thin_dots_square', 'planar', 1, (0, 0, 0), (.5, .5, .5), {'layer': {'type': 'square', 'dotWidth': .3, 'transWidth': 0.0}}, 'dots'),
    ('thin_grid_triangle_soft', 'planar', 1, (0, 0, 0), (.5, .5, .5), {'layer': {'type': 'triangle', 'lineWidth': .04, 'transWidth': .2}}, 'grid'),
    ('thin_grid_hexagon_soft', 'planar', 1, (0, 0, 0), (.5, .5, .5), {'layer': {'type': 'hexagon', 'lineWidth': .04, 'transWidth': .2}}, 'grid'),
    ('thin_dots_hexagon_soft', 'planar', 1, (0, 0, 0), (.5, .5, .5), {'layer': {'type': 'hexagon', 'dotWidth': .3, 'transWidth': .2}}, 'dots'),
]
# The layer channels the procedural cases set; each is put back to the layer's own default for a case that does not.
LAYER_CHANNELS = {'grid': ('type', 'lineWidth', 'transWidth', 'bias', 'gain'), 'dots': ('type', 'dotWidth', 'transWidth', 'bias', 'gain')}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def set_channel(item, name, value):
    try:
        item.channel(name).set(value)
    except Exception:
        lx.eval('item.channel {%s} {%s} item:{%s}' % (name, value, item.id))


try:
    from moonray_modo import host, rdla
    if OFF:
        import moonray_modo.native
        moonray_modo.native.environment_projections = lambda: False
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', SIZE[0]), ('resY', SIZE[1]), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    for light in scene.items('sunLight'):
        light.channel('render').set('off')
    camera = scene.renderCamera
    camera.position.set((0, 0, 0))
    camera.rotation.set((0, 0, 0))
    camera.channel('projType').set('spherical')
    # A small cube far below: MoonRay draws no environment in a scene with no geometry.
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    for attribute, value in (('sizeX', .01), ('sizeY', .01), ('sizeZ', .01), ('cenY', -50.0)):
        lx.eval('tool.attr prim.cube %s %s' % (attribute, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    environment = next(iter(scene.items('environment')))
    material = next((i for i in environment.children() if i.type == 'envMaterial'), None)
    if material is not None:
        material.channel('type').set('constant')
        for axis in 'RGB':
            material.channel('zenColor.' + axis).set(0.0)
    lx.eval('clip.addStill {%s}' % IMAGE)
    clip = scene.items('videoStill')[-1]
    lx.eval('clip.addStill {%s}' % str(pathlib.Path(IMAGE).with_name('uv_sq.exr')))
    clips = {'uv_code': clip, 'uv_sq': scene.items('videoStill')[-1]}
    BLENDING = None
    layers = {}
    defaults = {}

    def layer_for(kind):
        if kind in layers:
            return layers[kind]
        lx.eval('item.create %s' % ('imageMap' if kind == 'image' else kind))
        layer = scene.selected[0]
        defaults[kind] = {c: layer.channel(c).get() for c in LAYER_CHANNELS.get(kind, ())}
        lx.eval('texture.parent {%s} %d item:{%s}' % (environment.id, len(environment.children()), layer.id))
        if kind == 'image':
            lx.eval('select.item {%s} set' % layer.id)
            lx.eval('texture.setIMap {%s}' % clip.id)
        layer.channel('effect').set('envColor')
        layers[kind] = layer
        return layer

    for name, projection, axis, rotation, size, extra, kind in CASES:
        if ONLY and name not in ONLY:
            continue
        entry = {}
        try:
            layer = layer_for(kind)
            for other_kind, other in layers.items():
                other.channel('enable').set(other_kind == kind)
            locator = next(i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
            if BLENDING is None:
                BLENDING = float(locator.channel('triplanarBlending').get())
                result['default_triplanar_blending'] = BLENDING
            locator.channel('projType').set(projection)
            set_channel(locator, 'projAxis', axis)
            locator.position.set(extra.get('pos', (0, 0, 0)))
            locator.rotation.set(rotation, degrees=True)
            locator.scale.set(size)
            for channel_name, default in (('wrapU', 1.0), ('wrapV', 1.0), ('uvRotation', 0.0), ('m02', 0.0), ('m12', 0.0),
                                          ('tileU', 'repeat'), ('tileV', 'repeat'), ('triplanarBlending', BLENDING)):
                value = extra.get(channel_name, default)
                set_channel(locator, channel_name, value * 3.141592653589793 / 180 if channel_name == 'uvRotation' else value)
            if kind == 'image':
                lx.eval('select.item {%s} set' % layer.id)
                lx.eval('texture.setIMap {%s}' % clips[extra.get('image', 'uv_code')].id)
            layer.channel('opacity').set(extra.get('opacity', 1.0))
            for channel_name, default in defaults.get(kind, {}).items():
                set_channel(layer, channel_name, extra.get('layer', {}).get(channel_name, default))
            if kind in LAYER_CHANNELS:
                entry['layer'] = {c: str(layer.channel(c).get()) for c in LAYER_CHANNELS[kind]}
            entry['locator'] = {c: str(locator.channel(c).get()) for c in ('projType', 'projAxis', 'wrapU', 'wrapV', 'uvRotation', 'tileU', 'tileV',
                                                                         'm02', 'm12', 'triplanarBlending')}
            entry['matrix'] = host.world_matrix(locator)
            for index, view in enumerate(VIEWS if CUBE else [extra.get('view', (0, 0, 0))]):
                label = '%s_v%d' % (name, index) if CUBE else name
                if CUBE:
                    camera.channel('projType').set('persp')
                    for channel_name, value in (('focalLen', .018), ('apertureX', .036), ('apertureY', .036)):
                        camera.channel(channel_name).set(value)
                else:
                    camera.channel('projType').set(extra.get('camera', 'spherical'))
                camera.rotation.set(view, degrees=True)
                entry['camera'] = {c: str(camera.channel(c).get()) for c in ('projType', 'focalLen', 'apertureX', 'apertureY', 'filmFit')}
                if not OFF:
                    lx.eval('!render.animation {%s} openexr' % str(out / ('modo_%s' % label)))
                snapshot = host.snapshot()
                (out / ('%s%s.rdla' % (label, TAG))).write_text(
                    rdla.scene_text(snapshot, SIZE[0], SIZE[1], 4, 0.0, str(out / ('moonray_%s%s.exr' % (label, TAG)))), encoding='utf-8')
                # The scene as the plugin reads it (for MoonLightIPR, tools/check_moonlightipr_session.py).
                kept = {k: v for k, v in snapshot.items() if not k.startswith('_')}
                (out / ('%s%s.json' % (label, TAG))).write_text(json.dumps(kept, default=str), encoding='utf-8')
            if CUBE:
                entry['views'] = len(VIEWS)
            environments = snapshot.get('environments') or []
            entry['environment_kind'] = environments[0]['kind'] if environments else None
            entry['warnings'] = [w for w in snapshot.get('warnings', []) if 'nvironment' in w][:6]
        except Exception:
            entry['error'] = traceback.format_exc()[-2500:]
        if OFF:
            result.setdefault('off', {})[name] = {k: entry.get(k) for k in ('environment_kind', 'warnings', 'error') if k in entry}
        else:
            result['cases'][name] = entry
        save()
except Exception:
    result['error'] = traceback.format_exc()
save()
