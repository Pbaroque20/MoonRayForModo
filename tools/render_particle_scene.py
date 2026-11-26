"""Render an RDLA exported by tools/probe_cl_blob_render.py with MoonRay (moonray.exe of a runtime), and write a PNG of
its beauty beside Modo's for a look, with the mean difference of their alpha and colour where both are given.

render_particle_scene.py <scene.rdla> <runtime folder> [Modo's EXR to compare with] [--samples N] [--exec_mode scalar|vector|xpu]
Writes <scene>.moonray.exr (its beauty), <scene>.moonray.png, and with Modo's picture <scene>.side.png (Modo left)."""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('scene')
    parser.add_argument('runtime')
    parser.add_argument('modo', nargs='?')
    parser.add_argument('--samples', type=int, default=0)
    parser.add_argument('--exec_mode', default='scalar')
    args = parser.parse_args()
    scene, runtime = Path(args.scene), Path(args.runtime)
    out = scene.with_suffix('.moonray.exr')
    env = dict(os.environ)
    env['PATH'] = str(runtime) + os.pathsep + env.get('PATH', '')
    env['RDL2_DSO_PATH'] = os.pathsep.join(str(p) for p in (runtime / 'rdl2dso', runtime) if p.is_dir())
    env['REZ_MOONRAY_ROOT'] = str(runtime)
    command = [str(runtime / 'moonray.exe'), '-in', str(scene), '-out', str(out), '-exec_mode', args.exec_mode]
    if args.samples:
        command += ['-pixel_samples', str(args.samples)]
    started = time.perf_counter()
    done = subprocess.run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (scene.with_suffix('.moonray.log')).write_bytes(done.stdout)
    print('moonray exit', done.returncode, 'in %.1f s' % (time.perf_counter() - started))
    if done.returncode:
        print(done.stdout.decode(errors='replace')[-2000:])
        raise SystemExit(1)
    tool = runtime / 'oiiotool.exe'
    png = scene.with_suffix('.moonray.png')
    subprocess.run([str(tool), str(out), '--ch', 'R,G,B', '--colorconvert', 'linear', 'sRGB', '-o', str(png)], env=env, check=True)
    if args.modo:
        side = scene.with_suffix('.side.png')
        subprocess.run([str(tool), args.modo, '--ch', 'R,G,B', '--colorconvert', 'linear', 'sRGB', str(png), '--mosaic', '2x1', '-o', str(side)], env=env, check=True)
        diff = subprocess.run([str(tool), args.modo, str(out), '--diff'], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        print(diff.stdout.decode(errors='replace')[-600:])


if __name__ == '__main__':
    main()
