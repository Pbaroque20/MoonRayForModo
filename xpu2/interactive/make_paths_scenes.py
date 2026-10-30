"""Untextured fixtures for the path tracer's bounces (PATH_TRACER.md, phase 1).

make_paths_scenes.py --output <new folder>

A Cornell box: a room open toward the camera, red and green side walls, two boxes and a rectangular light under
the ceiling, all diffuse, written as RDLA at 64 and 1024 samples a pixel with a report in the form of the large
fixtures' (resolution and scenes), so run_paths_benchmark.py can take it with --fixtures."""
import argparse
import json
from pathlib import Path

WHITE, RED, GREEN = (0.7, 0.7, 0.7), (0.7, 0.1, 0.1), (0.1, 0.7, 0.1)


def quad(a, b, c, d):
    return [a, b, c, d], [0, 1, 2, 0, 2, 3]


def box(x0, x1, y0, y1, z0, z1):
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1), (x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)]
    faces = [(4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]  # no bottom face
    tris = []
    for a, b, c, d in faces:
        tris += [a, b, c, a, c, d]
    return v, tris


def scene(grid):
    meshes = [
        ('floor', quad((-3, -3, 0), (3, -3, 0), (3, -3, -6), (-3, -3, -6)), WHITE),
        ('ceiling', quad((-3, 3, 0), (-3, 3, -6), (3, 3, -6), (3, 3, 0)), WHITE),
        ('back', quad((-3, -3, -6), (3, -3, -6), (3, 3, -6), (-3, 3, -6)), WHITE),
        ('left', quad((-3, -3, 0), (-3, -3, -6), (-3, 3, -6), (-3, 3, 0)), RED),
        ('right', quad((3, -3, 0), (3, 3, 0), (3, 3, -6), (3, -3, -6)), GREEN),
        ('tall', box(-1.8, -0.4, -3, 0, -4.5, -3), WHITE),
        ('short', box(0.4, 1.9, -3, -1.5, -2.8, -1.3), WHITE),
    ]
    lines = [
        'SceneVariables { ["image_width"]=256, ["image_height"]=256, ["pixel_samples"]=%d, ["sampling_mode"]=0, ["frame"]=0,' % grid,
        ' ["pixel_filter"]=0, ["pixel_filter_width"]=1.0, ["bsdf_samples"]=1, ["light_samples"]=1, ["max_depth"]=3,',
        ' ["max_diffuse_depth"]=3, ["russian_roulette_threshold"]=0.0, ["sample_clamping_value"]=0.0, ["lights_visible_in_camera"]=false, ["two_stage_output"]=false, ["enable_motion_blur"]=false, ["enable_dof"]=false }',
        'PerspectiveCamera("/camera") { ["node_xform"]=Mat4(1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,10,1), ["focal"]=50.0,',
        ' ["film_width_aperture"]=36.0, ["near"]=0.001, ["far"]=1000.0 }',
        'SceneVariables { ["camera"]=PerspectiveCamera("/camera") }',
        # Facing down: the light shines down its local -Z, turned to world -Y.
        'RectLight("/panel_light") { ["node_xform"]=Mat4(1,0,0,0, 0,0,-1,0, 0,1,0,0, 0,2.95,-3,1), ["width"]=2.0, ["height"]=2.0, ["intensity"]=0.02 }',
        'LightSet("/lights") { RectLight("/panel_light") }',
        'RenderOutput("/beauty") { ["file_name"]="beauty.exr", ["result"]=0, ["channel_format"]=0, ["compression"]=1 }',
        'RenderOutput("/alpha") { ["file_name"]="beauty.exr", ["result"]=1, ["channel_format"]=0, ["compression"]=1 }',
    ]
    for i, (name, (verts, tris), color) in enumerate(meshes):
        lines.append('UsdPreviewSurface("/m%d") { ["diffuseColor"]=Rgb(%g,%g,%g), ["useSpecularWorkflow"]=1, ["specularColor"]=Rgb(0,0,0) }' % ((i,) + color))
        lines.append('RdlMeshGeometry("/%s") { ["vertex_list"]={%s}, ["face_vertex_count"]={%s}, ["vertices_by_index"]={%s}, ["is_subd"]=false, ["smooth_normal"]=false }' % (
            name, ','.join('Vec3(%g,%g,%g)' % v for v in verts), ','.join(['3'] * (len(tris) // 3)), ','.join(map(str, tris))))
    lines.append('GeometrySet("/geometry") { %s }' % ','.join('RdlMeshGeometry("/%s")' % m[0] for m in meshes))
    lines.append('Layer("/layer") { %s }' % ','.join('{ RdlMeshGeometry("/%s"), "", UsdPreviewSurface("/m%d"), LightSet("/lights") }' % (m[0], i)
                                                    for i, m in enumerate(meshes)))
    lines.append('SceneVariables { ["layer"]=Layer("/layer") }')
    return '\n'.join(lines) + '\n'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = {'cases': {'cornell': {'resolution': [256, 256], 'domain': 'diffuse, untextured, one rectangular light',
                                    'scenes': {}}}}
    for grid in (8, 32):
        d = out / 'cornell' / f'grid-{grid}' / 'frozen'
        (d / 'assets').mkdir(parents=True)
        (d / 'scene.rdla').write_text(scene(grid), encoding='utf-8')
        report['cases']['cornell']['scenes'][str(grid)] = str(d / 'scene.rdla')
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(out / 'report.json')


if __name__ == '__main__':
    main()
