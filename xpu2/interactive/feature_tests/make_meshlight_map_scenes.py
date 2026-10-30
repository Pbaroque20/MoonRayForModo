"""Mesh lights with a map shader: make_meshlight_map_scenes.py <folder> <texture.tx> <pixel samples>. The light scenes'
arch of quads (uvs a vertex) and ring of triangles and a hexagon, their light's map_shader a checkerboard, an image
and a world-space noise."""
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
src = (here / 'make_light_scenes2.py').read_text(encoding='utf-8')
defs = src[:src.index('CASES = {')]
folder = Path(sys.argv[1]).resolve()
ns = {'__file__': str(here / 'make_light_scenes2.py')}
exec(compile(defs, 'make_light_scenes2.py', 'exec'), ns)
BASE, GEOM, LAYER, FILL, mesh, tex = ns['BASE'], ns['GEOM'], ns['LAYER'], ns['FILL'], ns['mesh'], ns['tex']
arch_v, arch_f, ring_v, ring_f = ns['arch_v'], ns['arch_f'], ns['ring_v'], ns['ring_f']

# The arch with uvs a vertex across and along it.
arch_uv = ', ["uv_list"]={%s}' % ','.join('Vec2(%g,%g)' % (i // 2 / 8.0, i % 2) for i in range(len(arch_v)))
ARCH_UV = mesh('/emitter', arch_v, arch_f, arch_uv)
RING = mesh('/emitter', ring_v, ring_f)
MAPS = '\n'.join([
    'CheckerboardMap("/lc") { ["num_u_tiles"]=8, ["num_v_tiles"]=2, ["color_A"]=Rgb(1,1,1), ["color_B"]=Rgb(0.1,0.2,0.6) }',
    'ImageMap("/li") { ["texture"]="%s" }' % tex,
    'NoiseMap_v2("/ln") { ["space"]=2, ["frequency_multiplier"]=2.0, ["color_A"]=Rgb(0.1,0.1,0.1), ["color_B"]=Rgb(1,0.9,0.7) }',
]) + '\n'
CASES = {
    'mlm-checker': (FILL + MAPS + 'MeshLight("/key") { ["geometry"]=RdlMeshGeometry("/emitter"), ["intensity"]=3, ["map_shader"]=CheckerboardMap("/lc"), ["visible_in_camera"]=1 }\n', ARCH_UV),
    'mlm-image': (FILL + MAPS + 'MeshLight("/key") { ["geometry"]=RdlMeshGeometry("/emitter"), ["intensity"]=3, ["map_shader"]=ImageMap("/li"), ["visible_in_camera"]=1 }\n', ARCH_UV),
    'mlm-noise-tris': (FILL + MAPS + 'MeshLight("/key") { ["geometry"]=RdlMeshGeometry("/emitter"), ["intensity"]=4, ["map_shader"]=NoiseMap_v2("/ln"), ["visible_in_camera"]=1 }\n', RING),
}
folder.mkdir(parents=True, exist_ok=True)
for name, (light, extra) in CASES.items():
    lights = ['EnvLight("/fill")', 'MeshLight("/key")']
    text = BASE + light + 'LightSet("/lights") { %s }\n' % ', '.join(lights) + GEOM + extra + LAYER
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(' '.join(CASES))
