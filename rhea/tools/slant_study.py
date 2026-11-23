"""How Rhea's realtime frame in XPU2's session fares by how slanted the surface is to the camera (rhea/DESIGN.md 23):
a scene rendered as a realtime frame by the session alone with Rhea (its masks written, XPU2_SESSION_RHEA_DEBUG) and
with XPU2, scored against a reference, each pixel binned by its facing |N.z| (the camera-space normal output's depth
part: 1 facing the camera, 0 edge on).

slant_study.py --exe <runtime-xpu2/moonray_xpu2.exe> --in <scene file> [--in <more>] --reference <film order .rgba>
               --width W --height H --output <new folder> [--samples 32] [--mode 1] [--cache <folder>]
               [--optix-cache <folder>] [--shader-marks <folder>] [--rhea-env KEY=VALUE ...]
"""
import argparse
import array
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from camera_cases import realtime  # noqa: E402
from images import errors, read_rgba  # noqa: E402

NORMAL = ('RenderOutput("/rhea_normal") { ["file_name"] = "rhea.exr", ["channel_name"] = "rhea_normal", ["channel_format"] = 0, '
          '["result"] = 3, ["state_variable"] = 2 }\n')


def pfm(path, w, h):
    data = path.read_bytes()
    parts = data.split(b'\n', 3)
    pw, ph = map(int, parts[1].split())
    ch = 3 if parts[0].strip() == b'PF' else 1
    a = array.array('f')
    a.frombytes(parts[3][:pw * ph * 4 * ch])
    if float(parts[2]) > 0:
        a.byteswap()
    out = array.array('f', [1.0]) * (w * h * 4)
    for i in range(w * h):
        for c in range(3):
            out[4 * i + c] = a[ch * i + (c if ch == 3 else 0)]
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--exe', type=Path, required=True)
    p.add_argument('--in', dest='scenes', type=Path, action='append', required=True)
    p.add_argument('--reference', type=Path, required=True)
    p.add_argument('--width', type=int, required=True)
    p.add_argument('--height', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--samples', type=int, default=32)
    p.add_argument('--mode', default='1')
    p.add_argument('--cache', type=Path)
    p.add_argument('--optix-cache', type=Path)
    p.add_argument('--shader-marks', type=Path)
    p.add_argument('--rhea-env', action='append', default=[])
    p.add_argument('--oiiotool', type=Path, default=HERE.parents[1] / 'toolchain/msys64/ucrt64/bin/oiiotool.exe')
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    W, H = a.width, a.height
    env = dict(os.environ)
    for k, v in (('OPTIX_CACHE_PATH', a.optix_cache), ('XPU2_SHADER_MARKS', a.shader_marks), ('MOONRAY_MODO_CACHE', a.cache)):
        if v:
            env[k] = str(v.resolve())
    (a.output / 'realtime.rdla').write_text(realtime(a.samples) + NORMAL, encoding='utf-8')
    report = {}
    for name, engine in (('rhea', 'rhea'), ('xpu2', 'xpu2')):
        run = a.output / name
        run.mkdir()
        debug = run / 'debug'
        debug.mkdir()
        extra = dict(kv.split('=', 1) for kv in a.rhea_env) if engine == 'rhea' else {}
        command = [str(a.exe), 'render'] + sum((['-in', str(s.resolve())] for s in a.scenes), []) + \
                  ['-in', str((a.output / 'realtime.rdla').resolve()), '-out', 'beauty.exr', '--mode', a.mode]
        done = subprocess.run(command, cwd=run, env=dict(env, XPU2_SESSION_RT_ENGINE=engine, XPU2_SESSION_RHEA_DEBUG=str(debug.resolve()), **extra),
                              capture_output=True, text=True, timeout=3600)
        (run / 'session.log').write_text(done.stdout + done.stderr, encoding='utf-8')
        info = {'exit': done.returncode, 'lines': [l for l in done.stdout.splitlines() if 'Rhea' in l or 'finished in' in l or 'FALLBACK' in l][-4:]}
        subprocess.run([str(a.oiiotool), str(run / 'beauty.exr'), '--ch', 'R,G,B', '-o', str(run / 'beauty.pfm')], capture_output=True)
        subprocess.run([str(a.oiiotool), str(run / 'rhea.exr'), '--ch', 'rhea_normal.x,rhea_normal.y,rhea_normal.z', '-o', str(run / 'normal.pfm')],
                       capture_output=True)
        report[name] = info
        print(name, *info['lines'], sep='\n  ', flush=True)
    ref = read_rgba(a.reference, W, H)
    rhea, xpu2 = pfm(a.output / 'rhea' / 'beauty.pfm', W, H), pfm(a.output / 'xpu2' / 'beauty.pfm', W, H)
    for name, img in (('rhea', rhea), ('xpu2', xpu2)):
        e = errors(img, ref, W, H)
        report[name].update(relative_mse=e['relative_mse'], block_error=e['block_error'], mean_ratio=e['mean_ratio'])
        print('%s: relMSE %.3e block %.3e ratio %.5f' % (name, e['relative_mse'], e['block_error'], e['mean_ratio']), flush=True)
    normal_path = a.output / 'rhea' / 'normal.pfm'
    mask_path = a.output / 'rhea' / 'debug' / 'mask.rgba'
    if normal_path.exists() and mask_path.exists():
        normal = pfm(normal_path, W, H)
        mask = read_rgba(mask_path, W, H)
        bins = {}
        for i in range(W * H):
            nz = abs(normal[4 * i + 2])
            if normal[4 * i] == 0 and normal[4 * i + 1] == 0 and nz == 0:
                key = 'nothing'
            else:
                key = '%.1f-%.1f' % (min(0.9, int(nz * 10) / 10), min(1.0, int(nz * 10) / 10 + 0.1))
            b = bins.setdefault(key, {'pixels': 0, 'verified': 0, 'phase1': 0, 'gap': 0, 'edge': 0, 'rhea_se': 0.0, 'xpu2_se': 0.0, 'ref': 0.0})
            m = mask[4 * i]
            b['pixels'] += 1
            b['verified'] += m > 0.25
            b['phase1'] += m > 0.75
            state = round(mask[4 * i + 1] * 3)
            b['gap'] += m > 0.25 and state == 2
            b['edge'] += m > 0.25 and state == 3
            for c in range(3):
                b['rhea_se'] += (rhea[4 * i + c] - ref[4 * i + c]) ** 2
                b['xpu2_se'] += (xpu2[4 * i + c] - ref[4 * i + c]) ** 2
                b['ref'] += ref[4 * i + c] ** 2
        print('facing |N.z|   pixels  verified  phase 1  verified but a gap / a light edge   Rhea MSE / XPU2 MSE', flush=True)
        for key in sorted(bins):
            b = bins[key]
            print('  %-9s %8d   %5.1f%%   %5.1f%%      %5.1f%% / %5.1f%%                 %.2e / %.2e' % (
                key, b['pixels'], 100 * b['verified'] / b['pixels'], 100 * b['phase1'] / b['pixels'], 100 * b['gap'] / b['pixels'],
                100 * b['edge'] / b['pixels'], b['rhea_se'] / (3 * b['pixels']), b['xpu2_se'] / (3 * b['pixels'])), flush=True)
        report['by_facing'] = bins
    (a.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
