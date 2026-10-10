"""Measure how much of a texture MoonLightIPR's denoiser keeps.

Usage: check_moonlightipr_denoise.py <moonray-runtime> <file.mtlx> [uv repeat] [camera distance]
Run outside Modo after tools/build_moonlightipr.py. The material is rendered on a ball once without the denoiser at many
samples, the picture to aim for, then with it at few, in each way of using it. Two numbers per picture: how far it is
from the one to aim for, and how much of that picture's fine detail (what a blur of it loses) is still there."""
import math
import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_moonlightipr_session as fixture
import compare_moonlightipr as compare
import render_materialx
from moonray_modo import coordinates, materialx, moonlightipr_scene, native, nodes

WIDTH, HEIGHT = compare.WIDTH, compare.HEIGHT
MODES = (('as it was', {'MOONLIGHTIPR_DENOISE': 'plain', 'MOONLIGHTIPR_DENOISE_KEEP': '0'}),
         ('light alone', {'MOONLIGHTIPR_DENOISE_KEEP': '0'}),
         ('light alone, kept share', {}))
SAMPLES = (16, 64, 256, 1024)


def scene_of(source, repeat, distance):
    graph = materialx.read(source)
    vertices, faces, uvs = render_materialx.ball(repeat)
    base = fixture.snapshot()
    root = graph['nodes'][graph['root']]
    material = {'name': source.stem, 'color': [.8, .8, .8], 'roughness': .4, 'shader': 'DwaBaseMaterial', 'native_shader': root['type'],
                'native_parameters': root.get('parameters', {}), 'node_graph': graph, 'node_override': True}
    return dict(base, materials={'': {'color': [.35, .35, .35], 'roughness': .7}, 'mtlx': material}, _environment=.6,
                camera={'matrix': fixture.look_at([2.6 * distance, 1.0 + 1.0 * distance, 3.6 * distance], [0, 1.0, 0]), 'focal_mm': 50.0, 'film_mm': 36.0},
                meshes=[base['meshes'][0], {'name': 'Ball', 'identity': 'ball', 'vertices': vertices, 'faces': faces, 'uvs': uvs, 'material': 'mtlx', 'smooth': True,
                                            'uv_sets': {layer['coordinate_key']: coordinates.transform_uv(layer, uvs) for layer in nodes.descriptors(graph)
                                                        if layer.get('projection', 'uv') == 'uv'}}])


def rendered(scene, runtime, folder, samples, denoise, settings):
    """One picture as luminance per pixel, shown as the eye would see it, from a session of its own."""
    kept = {key: os.environ.pop(key, None) for key in ('MOONLIGHTIPR_DENOISE', 'MOONLIGHTIPR_DENOISE_KEEP')}
    os.environ.update(settings)
    session = fixture.Session(folder)
    try:
        payload, _, _ = moonlightipr_scene.pack(scene, WIDTH, HEIGHT, scene.get('_environment', 0.0), set(), samples, denoise=denoise, runtime=runtime)
        session.send(payload)
        result = session.wait()
        if result['event'] != 'DONE':
            raise RuntimeError('MoonLightIPR rejected the scene')
        session.process.stdin.write(b'quit\n')
        session.process.stdin.flush()
        session.process.wait(timeout=10)
    finally:
        if session.process.poll() is None:
            session.process.kill()
        for key, value in kept.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value
    values = struct.unpack('<%df' % (WIDTH * HEIGHT * 3), result['pixels'])
    shown = lambda v: min(1.0, max(0.0, v)) ** (1 / 2.2)
    return [.2126 * shown(values[i]) + .7152 * shown(values[i + 1]) + .0722 * shown(values[i + 2]) for i in range(0, len(values), 3)], values


def blurred(image, radius=3):
    """A box blur, across then down."""
    def passed(source, step, limit, other):
        out = [0.0] * len(source)
        for b in range(other):
            for a in range(limit):
                low, high = max(0, a - radius), min(limit - 1, a + radius)
                index = (lambda k: b * WIDTH + k) if step == 1 else (lambda k: k * WIDTH + b)
                out[index(a)] = sum(source[index(k)] for k in range(low, high + 1)) / (high - low + 1)
        return out
    return passed(passed(image, 1, WIDTH, HEIGHT), WIDTH, HEIGHT, WIDTH)


def main():
    runtime = native.find_runtime(sys.argv[1])
    source = Path(sys.argv[2])
    repeat = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
    distance = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
    folder = fixture.BUILD / 'denoise'
    folder.mkdir(parents=True, exist_ok=True)
    os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
    scene = scene_of(source, repeat, distance)
    aim, _ = rendered(scene, runtime, folder, 8192, False, {})
    fine = [a - b for a, b in zip(aim, blurred(aim))]
    strength = sum(v * v for v in fine)
    # Only where the material is: the ground and sky have no detail to keep.
    print('%s: fine detail in the picture to aim for %.4f' % (source.stem, math.sqrt(strength / len(fine))))
    print('%-26s' % 'samples' + ''.join('%18d' % count for count in SAMPLES))
    rows = [('no denoiser', None)] + list(MODES)
    for title, settings in rows:
        cells = []
        for count in SAMPLES:
            image, values = rendered(scene, runtime, folder, count, settings is not None, settings or {})
            error = math.sqrt(sum((a - b) ** 2 for a, b in zip(image, aim)) / len(aim))
            detail = [a - b for a, b in zip(image, blurred(image))]
            # The share of the aimed-for detail that is there, in the same places.
            share = sum(a * b for a, b in zip(detail, fine)) / max(strength, 1e-12)
            cells.append('%9.4f %6.0f%% ' % (error, 100 * share))
            name = '%s_%s_%d.pfm' % (source.stem, title.replace(' ', '_').replace(',', ''), count)
            (folder / name).write_bytes(('PF\n%d %d\n-1.0\n' % (WIDTH, HEIGHT)).encode() + struct.pack('<%df' % len(values), *values))
        print('%-26s' % title + ''.join(cells))
    print('each cell: distance from the picture to aim for, then the share of its fine detail kept')


if __name__ == '__main__':
    main()
