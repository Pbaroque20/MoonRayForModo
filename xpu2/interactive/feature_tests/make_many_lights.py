"""Many-light scenes: make_many_lights.py <folder> <pixel samples>. 48 small lights (spheres, rects, disks, spots,
cylinders) over the floor, uniform (light_sampling_mode 0) and adaptive (1) light sampling."""
import math
import sys
from pathlib import Path

folder, samples = Path(sys.argv[1]).resolve(), int(sys.argv[2])
folder.mkdir(parents=True, exist_ok=True)
src = (Path(__file__).parent / 'make_light_scenes.py').read_text(encoding='utf-8')
ns = {'samples': samples}
exec(src[src.index('BASE = '):src.index('FILL = ')], ns)
BASE, GEOM, LAYER = ns['BASE'], ns['GEOM'], ns['LAYER']
lights = ['EnvLight("/fill") { ["intensity"]=0.03 }']
k = 0
for row in range(6):
    for col in range(8):
        x, z = -5.6 + col * 1.6, -2.5 + row * 1.3
        y = 2.6 + 0.4 * ((row + col) % 3)
        hue = [(1, 0.5, 0.3), (0.3, 0.7, 1), (0.6, 1, 0.4), (1, 1, 0.8), (1, 0.4, 0.9)][k % 5]
        c = 'Rgb(%g,%g,%g)' % hue
        kind = k % 5
        if kind == 0:
            l = 'SphereLight("/l%d") { ["node_xform"]=Mat4(1,0,0,0, 0,1,0,0, 0,0,1,0, %g,%g,%g,1), ["radius"]=0.12, ["intensity"]=3, ["color"]=%s }' % (k, x, y, z, c)
        elif kind == 1:
            l = 'RectLight("/l%d") { ["node_xform"]=Mat4(1,0,0,0, 0,0,-1,0, 0,1,0,0, %g,%g,%g,1), ["width"]=0.4, ["height"]=0.3, ["intensity"]=3, ["color"]=%s }' % (k, x, y, z, c)
        elif kind == 2:
            l = 'DiskLight("/l%d") { ["node_xform"]=Mat4(1,0,0,0, 0,0,-1,0, 0,1,0,0, %g,%g,%g,1), ["radius"]=0.2, ["intensity"]=3, ["color"]=%s, ["sidedness"]=2 }' % (k, x, y, z, c)
        elif kind == 3:
            l = 'SpotLight("/l%d") { ["node_xform"]=Mat4(1,0,0,0, 0,0,-1,0, 0,1,0,0, %g,%g,%g,1), ["lens_radius"]=0.1, ["outer_cone_angle"]=60, ["inner_cone_angle"]=30, ["intensity"]=6, ["color"]=%s }' % (k, x, y, z, c)
        else:
            l = 'CylinderLight("/l%d") { ["node_xform"]=Mat4(0,1,0,0, -1,0,0,0, 0,0,1,0, %g,%g,%g,1), ["radius"]=0.05, ["height"]=0.6, ["intensity"]=3, ["color"]=%s }' % (k, x, y, z, c)
        lights.append(l)
        k += 1
names = [l.split('(')[0] + '("' + l.split('"')[1] + '")' for l in lights]
for name, mode in (('many-uniform', 0), ('many-adaptive', 1)):
    base = BASE.replace('["two_stage_output"]=false }', '["two_stage_output"]=false, ["light_sampling_mode"]=%d, ["light_sampling_quality"]=0.5 }' % mode)
    text = base + '\n'.join(lights) + '\nLightSet("/lights") { %s }\n' % ', '.join(names) + GEOM + LAYER
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print('many-uniform many-adaptive')
