"""Camera test scenes: make_camera_scenes.py <folder>. The mirror-key scene (beauty1) seen through each MoonRay camera
type and lens setting, with beauty, alpha and depth in one file; plus a ring-shaped bokeh image (PFM)."""
import re
import struct
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
folder = Path(sys.argv[1]).resolve()
folder.mkdir(parents=True, exist_ok=True)
base = (here / 'beauty1' / 'mirror-key.rdla').read_text(encoding='utf-8')
XFORM = 'Mat4(1,0,0,0, 0,0.978148,-0.207912,0, 0,0.207912,0.978148,0, 0,2.0,7.5,1)'

# A ring with a bright notch: an asymmetric shape shows a flipped or turned image.
ring = folder / 'bokeh-ring.pfm'
W = H = 64
rows = []
for y in range(H):
    row = []
    for x in range(W):
        u, v = (x + 0.5) / W * 2 - 1, (y + 0.5) / H * 2 - 1
        r = (u * u + v * v) ** 0.5
        val = 1.0 if 0.6 < r < 0.95 else 0.0
        if u > 0.3 and abs(v) < 0.2 and r < 0.95:
            val = 3.0
        row.append(val)
    rows.append(row)
with open(ring, 'wb') as f:
    f.write(b'Pf\n%d %d\n-1.0\n' % (W, H))
    for row in rows:  # PFM rows run from the bottom
        f.write(struct.pack('<%df' % W, *row))

persp = 'PerspectiveCamera("/camera") { ["node_xform"]=%s, ["focal"]=35.0, ["film_width_aperture"]=36.0, ["near"]=0.01, ["far"]=1000.0%s }'
dof = ', ["dof"]=true, ["dof_aperture"]=2.8, ["dof_focus_distance"]=7.0'
cases = {
    'dof-disk': (persp % (XFORM, dof), {}),
    'dof-poly': (persp % (XFORM, dof + ', ["bokeh"]=true, ["bokeh_sides"]=6, ["bokeh_angle"]=20.0'), {}),
    'dof-image': (persp % (XFORM, dof + ', ["bokeh"]=true, ["bokeh_image"]="%s"' % ring.as_posix()), {}),
    'offsets-stereo': (persp % (XFORM, ', ["horizontal_film_offset"]=3.0, ["vertical_film_offset"]=-2.0, ["pixel_aspect_ratio"]=1.25, '
                                     '["stereo_view"]=1, ["stereo_interocular_distance"]=0.4, ["stereo_convergence_distance"]=8.0'), {}),
    'stereo-right-dof': (persp % (XFORM, dof + ', ["stereo_view"]=2, ["stereo_interocular_distance"]=0.6'), {}),
    'ortho': ('OrthographicCamera("/camera") { ["node_xform"]=%s, ["film_width_aperture"]=12.0, ["horizontal_film_offset"]=0.5, '
              '["vertical_film_offset"]=0.3, ["near"]=0.01, ["far"]=1000.0 }' % XFORM, {}),
    'ortho-dof': ('OrthographicCamera("/camera") { ["node_xform"]=%s, ["film_width_aperture"]=12.0, ["near"]=0.01, ["far"]=1000.0, '
                  '["dof"]=true, ["dof_aperture"]=0.1, ["dof_focus_distance"]=7.0 }' % XFORM, {}),
    'sph-legacy': ('SphericalCamera("/camera") { ["node_xform"]=%s, ["near"]=0.01, ["far"]=1000.0 }' % XFORM, {}),
    'sph-range': ('SphericalCamera("/camera") { ["node_xform"]=%s, ["near"]=0.01, ["far"]=1000.0, ["min_latitude"]=-40.0, ["max_latitude"]=40.0, '
                  '["min_longitude"]=-90.0, ["max_longitude"]=90.0, ["latitude_zoom_offset"]=5.0, ["focal"]=25.0 }' % XFORM, {}),
    'sph-inside': ('SphericalCamera("/camera") { ["node_xform"]=Mat4(1,0,0,0, 0,1,0,0, 0,0,1,0, 0,1.5,0,1), ["near"]=0.01, ["far"]=1000.0, '
                   '["min_latitude"]=-60.0, ["max_latitude"]=60.0, ["min_longitude"]=-120.0, ["max_longitude"]=120.0, ["inside_out"]=true, ["offset_radius"]=6.0 }', {}),
    'fish-stereo': ('FisheyeCamera("/camera") { ["node_xform"]=%s, ["near"]=0.01, ["far"]=1000.0, ["mapping"]=0, ["format"]=0, ["fov"]=170.0 }' % XFORM, {}),
    'fish-equid': ('FisheyeCamera("/camera") { ["node_xform"]=%s, ["near"]=0.01, ["far"]=1000.0, ["mapping"]=1, ["format"]=1, ["fov"]=140.0, ["zoom"]=1.2 }' % XFORM, {}),
    'fish-solid': ('FisheyeCamera("/camera") { ["node_xform"]=%s, ["near"]=0.01, ["far"]=1000.0, ["mapping"]=2, ["format"]=2, ["fov"]=180.0 }' % XFORM, {}),
    'fish-ortho': ('FisheyeCamera("/camera") { ["node_xform"]=%s, ["near"]=0.01, ["far"]=1000.0, ["mapping"]=3, ["format"]=0, ["fov"]=180.0 }' % XFORM, {}),
    'dome': ('DomeMaster3DCamera("/camera") { ["node_xform"]=%s, ["near"]=0.01, ["far"]=1000.0, ["FOV_horizontal_angle"]=120.0, ["FOV_vertical_angle"]=70.0, '
             '["stereo_view"]=2, ["stereo_interocular_distance"]=0.5, ["stereo_convergence_distance"]=9.0 }' % XFORM, {}),
    'dome-zenith': ('DomeMaster3DCamera("/camera") { ["node_xform"]=Mat4(1,0,0,0, 0,0,-1,0, 0,1,0,0, 0,1.5,3,1), ["near"]=0.01, ["far"]=1000.0, '
                    '["FOV_horizontal_angle"]=180.0, ["FOV_vertical_angle"]=180.0, ["zenith_mode"]=true, ["flip_ray_x"]=true, ["stereo_view"]=1 }', {}),
    'overscan': (persp % (XFORM, dof), {'aperture_window': '{0, 0, 320, 200}', 'region_window': '{-16, -10, 336, 210}'}),
    'subview': (persp % (XFORM, ''), {'sub_viewport': '{40, 30, 250, 170}'}),
    'res2': (persp % (XFORM, ''), {'res': '2.0', 'texture_blur': '0.5'}),
}
outputs = ('RenderOutput("/beauty") { ["file_name"]="OUTPUT", ["result"]=0, ["channel_format"]=1, ["compression"]=1 }\n'
           'RenderOutput("/alpha") { ["file_name"]="OUTPUT", ["result"]=1, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="A" }\n'
           'RenderOutput("/depth") { ["file_name"]="OUTPUT", ["result"]=2, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="Z" }\n')
for name, (camera, sv) in cases.items():
    t = base
    t = re.sub(r'^PerspectiveCamera\("/camera"\) \{[^\n]*\}$', lambda m: camera, t, count=1, flags=re.M)
    cls = camera.split('(')[0]
    t = t.replace('SceneVariables { ["camera"]=PerspectiveCamera("/camera") }', 'SceneVariables { ["camera"]=%s("/camera") }' % cls)
    if 'dof' in camera:
        t = t.replace('["enable_dof"]=false', '["enable_dof"]=true')
    for k, v in sv.items():
        t = t.replace('SceneVariables { ["', 'SceneVariables { ["%s"]=%s, ["' % (k, v), 1)
    t = re.sub(r'^RenderOutput\("/beauty"\) \{[^\n]*\}\n', lambda m: outputs, t, count=1, flags=re.M)
    assert outputs in t and camera in t, name
    (folder / (name + '.rdla')).write_text(t, encoding='utf-8')
print(len(cases), 'cases')
