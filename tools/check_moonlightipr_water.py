"""MoonLightIPR's water against MoonRay's: a flat plane of the ocean demo's material (DwaBaseMaterial, dark albedo,
roughness 0.03, refractive index 1.33), under a plain white sky and nothing else, seen from three heights: steep, middle
and grazing. The plane's middle measured in each engine; the reflection should agree. Writes
test-results/moonlightipr-water/<case>.pfm/.exr and report.json. MOONRAY_RUNTIME the runtime, else the installed kit's."""
import json
import os
import pathlib
import struct
import subprocess
import sys
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
import check_moonlightipr_session as fixture  # noqa: E402
from moonray_modo import native, rdla  # noqa: E402

RUNTIME = pathlib.Path(os.environ.get('MOONRAY_RUNTIME') or pathlib.Path(os.environ['APPDATA']) / 'Luxology/Kits/MoonRayForModo/runtime')
W, H = fixture.WIDTH, fixture.HEIGHT
folder = ROOT / 'test-results/moonlightipr-water'
folder.mkdir(parents=True, exist_ok=True)
WATER = {'native_shader': 'DwaBaseMaterial', 'shader': 'DwaBaseMaterial', 'color': [0.004, 0.018, 0.026],
         'native_parameters': {'albedo': [0.004, 0.018, 0.026], 'roughness': 0.03, 'refractive_index': 1.33, 'metallic': 0.0}}


def scene(height):
    vertices = [[-50, 0, -50], [50, 0, -50], [50, 0, 50], [-50, 0, 50]]
    return {'camera': {'matrix': fixture.look_at([0, height, 10], [0, 0, 0]), 'focal_mm': 50.0, 'film_mm': 36.0},
            'materials': {'': WATER},
            'meshes': [{'name': 'Water', 'identity': 'water', 'vertices': vertices, 'faces': [[0, 3, 2, 1]], 'material': '',
                        'uvs': [[0, 0], [0, 1], [1, 1], [1, 0]]}],
            'lights': [], 'environments': [{'kind': 'constant', 'name': 'White', 'intensity': 1.0, 'zenith': [1, 1, 1], 'nadir': [1, 1, 1],
                                            'sky': [1, 1, 1], 'ground': [1, 1, 1]}]}


def middle_pfm(pixels):
    values = struct.unpack('<%df' % (W * H * 3), pixels)
    total = [0.0] * 3
    for y in range(H // 2 - 10, H // 2 + 10):
        for x in range(W // 2 - 10, W // 2 + 10):
            for c in range(3):
                total[c] += values[(y * W + x) * 3 + c]
    return [round(v / 400, 4) for v in total]


def middle_exr(path):
    out = subprocess.run([str(RUNTIME / 'oiiotool.exe'), str(path), '--cut', '20x20+%d+%d' % (W // 2 - 10, H // 2 - 10), '--printstats'],
                         env=native.environment(RUNTIME), capture_output=True, text=True)
    line = next(l for l in out.stdout.splitlines() if 'Stats Avg' in l)
    return [round(float(v), 4) for v in line.split(':')[1].split()[:3]]


def main():
    session = fixture.Session(folder)
    report = {}
    try:
        for name, height in (('steep', 20.0), ('middle', 5.0), ('grazing', 1.0)):
            made = scene(height)
            result = session.submit(made)
            fixture.write_images(folder / name, result['pixels'])
            target = folder / (name + '.exr')
            with mock.patch.object(native, 'default_runtime', return_value=str(RUNTIME)):
                text = rdla.scene_text(made, W, H, 8, 0.0, str(target))
            (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
            subprocess.run([str(RUNTIME / 'moonray.exe'), '-in', str(folder / (name + '.rdla')), '-out', str(target)],
                           env=native.environment(RUNTIME), capture_output=True, timeout=900)
            report[name] = {'moonlightipr': middle_pfm(result['pixels']), 'moonray': middle_exr(target)}
            print(name, report[name])
    finally:
        session.process.kill()
    (folder / 'report.json').write_text(json.dumps(report, indent=1))


if __name__ == '__main__':
    main()
