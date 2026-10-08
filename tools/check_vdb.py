"""Render an OpenVDB file through the plugin's VdbGeometry item, as a check that volume files come in.

The file is given to a VdbGeometry with a VdbVolume in it, lit by a sun and a grey sky, and rendered by
MoonRay. Usage: check_vdb.py <moonray-runtime> <file.vdb> [distance] [scale]"""
import math
import subprocess
import sys
import types
from pathlib import Path

root = Path(__file__).resolve().parents[1]
for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_moonlight_session as fixture
from moonray_modo import entities, native, rdla


def main():
    runtime = Path(sys.argv[1]).resolve()
    source = Path(sys.argv[2])
    distance = float(sys.argv[3]) if len(sys.argv) > 3 else 6.0
    scale = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
    out = root / 'test-results/vdb'
    out.mkdir(parents=True, exist_ok=True)
    grids = entities.vdb_grids(str(source))
    print('grids in the file:', grids)
    placed = [scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, 1]
    scene = {'camera': {'matrix': fixture.look_at([distance * .6, distance * .35, distance], [0, 0, 0]), 'focal_mm': 35.0, 'film_mm': 36.0},
             'materials': {'': {'color': [.5, .5, .5], 'roughness': .6}}, 'meshes': [],
             'lights': [{'kind': 'DistantLight', 'identity': 'sun', 'name': 'Sun', 'color': [1, .95, .85], 'intensity': 3.0, 'angle': 2.0,
                         'matrix': fixture.look_at([0, 0, 0], [-.5, -.8, -.4])}],
             'environments': [], '_environment': .4, 'width': 480, 'height': 360, 'warnings': [],
             'entities': [
                 {'identity': 'cloud', 'name': 'Cloud', 'class': 'VdbGeometry', 'matrix': placed,
                  'parameters': {'model': str(source).replace('\\', '/'), 'density_grid': grids[0] if grids else 'density', 'modo_volume': 'Smoke'}},
                 {'identity': 'smoke', 'name': 'Smoke', 'class': 'VdbVolume', 'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
                  'parameters': {}}]}
    target = out / (source.stem + '.exr')
    text = rdla.scene_text(scene, 480, 360, 3, .4, str(target))
    (out / (source.stem + '.rdla')).write_text(text, encoding='utf-8')
    for line in text.splitlines():
        if 'Vdb' in line or 'BaseVolume' in line or 'model' in line or 'grid' in line:
            print('  ', line.strip()[:160])
    done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(out / (source.stem + '.rdla'), target, 0, 'vectorized'),
                          env=native.environment(runtime), cwd=str(out), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900)
    log = done.stdout.decode(errors='replace')
    (out / (source.stem + '.log')).write_text(log)
    print('MoonRay exit', done.returncode, 'picture', target.is_file())
    for line in log.splitlines():
        if any(word in line for word in ('rror', 'arning', 'VDB', 'Vdb', 'vdb', 'olume', 'BVH memory')):
            print('  ', line.strip()[:170])
    if target.is_file():
        subprocess.run([str(runtime / 'oiiotool.exe'), str(target), '--ch', 'R,G,B', '--colorconvert', 'linear', 'sRGB', '-o', str(out / (source.stem + '.png'))],
                       env=native.environment(runtime))


if __name__ == '__main__':
    main()
