"""Render a MaterialX file on a ball, in MoonRay and in MoonLight, as the plugin would import it.

Usage: render_materialx.py <moonray-runtime> <file.mtlx> [uv repeat]"""
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_moonlight_session as fixture
import compare_moonlight as compare
from moonray_modo import materialx, native


def ball(repeat):
    rings, around = 48, 96
    vertices, faces, uvs = [], [], []
    for i in range(rings + 1):
        for j in range(around + 1):
            a, b = math.pi * i / rings, 2 * math.pi * j / around
            vertices.append([math.sin(a) * math.cos(b), 1.0 + math.cos(a), math.sin(a) * math.sin(b)])
    for i in range(rings):
        for j in range(around):
            corners = [i * (around + 1) + j, i * (around + 1) + j + 1, (i + 1) * (around + 1) + j + 1, (i + 1) * (around + 1) + j]
            faces.append(corners)
            uvs += [[repeat * (c % (around + 1)) / around, repeat * (1 - (c // (around + 1)) / rings)] for c in corners]
    return vertices, faces, uvs


def main():
    runtime = native.find_runtime(sys.argv[1])
    source = Path(sys.argv[2])
    repeat = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
    graph = materialx.read(source)
    folder = fixture.BUILD / 'compare'
    folder.mkdir(parents=True, exist_ok=True)
    os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
    vertices, faces, uvs = ball(repeat)
    base = fixture.snapshot()
    root = graph['nodes'][graph['root']]
    material = {'name': source.stem, 'color': [.8, .8, .8], 'roughness': .4, 'shader': 'DwaBaseMaterial', 'native_shader': root['type'],
                'native_parameters': root.get('parameters', {}), 'node_graph': graph, 'node_override': True}
    scene = dict(base, materials={'': {'color': [.35, .35, .35], 'roughness': .7}, 'mtlx': material}, _environment=.6,
                 camera={'matrix': fixture.look_at([2.6, 2.0, 3.6], [0, 1.0, 0]), 'focal_mm': 50.0, 'film_mm': 36.0},
                 meshes=[base['meshes'][0], {'name': 'Ball', 'identity': 'ball', 'vertices': vertices, 'faces': faces, 'uvs': uvs, 'material': 'mtlx', 'smooth': True}],
                 lights=fixture.snapshot()['lights'], environments=fixture.snapshot()['environments'])
    name = 'materialx_' + source.stem
    reference = compare.moonray(scene, runtime, folder, name)
    session = fixture.Session(folder)
    session.runtime = runtime
    try:
        try:
            preview, warnings = compare.moonlight(scene, session, name)
            a, b = compare.blocks(reference), compare.blocks(preview)
            ratios = sorted(y / x for x, y in zip(a, b) if x > 1e-3)
            print('MoonLight/MoonRay brightness %.3f, %d%% of tiles within 10%%' % (sum(b) / max(sum(a), 1e-12), 100 * sum(.9 <= r <= 1.1 for r in ratios) / len(ratios)))
            for warning in warnings:
                print('  MoonLight:', warning)
        except Exception as exc:
            print('MoonLight could not show it:', str(exc)[:300])
            preview = [0.0] * len(reference)
        compare.write_ppm(folder / (name + '.ppm'), reference, preview)
        print('picture:', folder / (name + '.ppm'))
        session.process.stdin.write(b'quit\n')
        session.process.stdin.flush()
        session.process.wait(timeout=10)
    finally:
        if session.process.poll() is None:
            session.process.kill()


if __name__ == '__main__':
    main()
