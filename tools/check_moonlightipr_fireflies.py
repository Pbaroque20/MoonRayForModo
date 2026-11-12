"""Fireflies in MoonLightIPR under different Render Settings: probe_cl_firefly_scene.py's scene (scene.pickle) rendered
at 640 x 360 with the same samples under each combination of Sample Clamp, Clamp From Bounce and Roughness Clamp. A
firefly is a pixel whose brightest channel is more than twice its eight neighbours' and above 0.2. For each:
how many there are, the brightest pixel, and the picture's mean (how much light the setting takes away). The pictures
are written as PNGs beside it. check_moonlightipr_fireflies.py <runtime folder> [samples]"""
import pathlib
import pickle
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
import compare_moonlightipr as compare
from moonray_modo import native

runtime = native.find_runtime(sys.argv[1])
samples = int(sys.argv[2]) if len(sys.argv) > 2 else 256
W, H = 640, 360
compare.WIDTH, compare.HEIGHT = W, H
compare.fixture.WIDTH, compare.fixture.HEIGHT = W, H
compare.MOONLIGHTIPR_SAMPLES = samples
compare.os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
folder = ROOT / 'test-results/fireflies'
base = pickle.loads((folder / 'scene.pickle').read_bytes())
CASES = [
    ('as the scene has it', {}),
    ('Sample Clamp 100, Roughness Clamp 1', {'sample_clamping_value': 100.0, 'roughness_clamping_factor': 1.0}),
    ('Roughness Clamp 1', {'roughness_clamping_factor': 1.0}),
    ('Sample Clamp 2', {'sample_clamping_value': 2.0}),
    ('Sample Clamp 1', {'sample_clamping_value': 1.0}),
    ('Sample Clamp 2, Roughness Clamp 1', {'sample_clamping_value': 2.0, 'roughness_clamping_factor': 1.0}),
    ('Sample Clamp 2, from bounce 0', {'sample_clamping_value': 2.0, 'sample_clamping_depth': 0}),
    ('Sample Clamp 1, from bounce 0', {'sample_clamping_value': 1.0, 'sample_clamping_depth': 0}),
    ('Sample Clamp 0.5, from bounce 0', {'sample_clamping_value': 0.5, 'sample_clamping_depth': 0}),
    ('Glossy bounces 1', {'max_glossy_depth': 1}),
    ('Glossy bounces 4', {'max_glossy_depth': 4}),
]


def fireflies(values):
    """Specks, by each pixel's brightest channel (a red speck is dim by luminance): more than twice the brightest of its
    eight neighbours and above 0.2."""
    top = [max(values[i * 3], values[i * 3 + 1], values[i * 3 + 2]) for i in range(W * H)]
    count = 0
    for y in range(1, H - 1):
        for x in range(1, W - 1):
            v = top[y * W + x]
            if v <= 0.2:
                continue
            around = max(top[(y + dy) * W + x + dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)
            if v > 2.0 * around:
                count += 1
    lum = [.2126 * values[i * 3] + .7152 * values[i * 3 + 1] + .0722 * values[i * 3 + 2] for i in range(W * H)]
    return count, max(top), sum(lum) / len(lum)


def png(values, path):
    """The picture as an 8-bit PNG through sRGB, values clipped at 1."""
    import struct
    import zlib
    encode = lambda v: round(255 * (12.92 * v if v <= .0031308 else 1.055 * v ** (1 / 2.4) - .055))
    rows = b''.join(b'\x00' + bytes(encode(min(1.0, max(0.0, v))) for v in values[y * W * 3:(y + 1) * W * 3]) for y in reversed(range(H)))
    chunk = lambda kind, data: struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', W, H, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(rows, 6)) + chunk(b'IEND', b''))


session = compare.fixture.Session(folder)
session.runtime = runtime
try:
    print('%d samples a pixel, %d x %d' % (samples, W, H))
    for index, (label, changed) in enumerate(CASES):
        scene = dict(base, _flat_out=True, render_settings=dict(base.get('render_settings') or {}, **changed))
        started = time.perf_counter()
        values = compare.moonlightipr(scene, session, 'case%d' % index)[0]
        count, brightest, mean = fireflies(values)
        png(values, folder / ('case%d.png' % index))
        print('%-36s fireflies %5d   brightest %8.2f   mean %.4f   (%.1f s)' % (label, count, brightest, mean, time.perf_counter() - started), flush=True)
finally:
    if session.process.poll() is None:
        session.process.kill()
