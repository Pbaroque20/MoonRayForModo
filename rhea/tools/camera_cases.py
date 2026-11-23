"""Rhea's camera kinds through XPU2's session (rhea/DESIGN.md 22): the test scene with each camera (depth of field,
motion blur, orthographic, spherical, fisheye, dome), rendered as a realtime frame by the session alone (moonray_xpu2
render) with Rhea and with XPU2 at the realtime samples, and by XPU2 at many samples for the reference; each scored
against it, with what Rhea's log says (frames, probes, verified, phase 1).

camera_cases.py --exe <runtime-xpu2/moonray_xpu2.exe> --scene <overflow/scene.rdla> --output <new folder>
                [--cases dof,motion,...] [--samples 32] [--reference 1024] [--mode 1]
                [--optix-cache <folder>] [--shader-marks <folder>]

Never writes anywhere but its output folder (a private OptiX cache and shader marks where given)."""
import argparse
import array
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / 'kit/MoonRayForModo/python'))
from images import errors  # noqa: E402

# The test scene's camera (overflow/scene.rdla).
CAMERA = 'Mat4(1,0,0,0, 0,0.978148,0.207912,0, 0,-0.207912,0.978148,0, 0,1.9,6.2,1)'
MOVED = 'Mat4(1,0,0,0, 0,0.978148,0.207912,0, 0,-0.207912,0.978148,0, 0.25,1.9,6.2,1)'
CASES = {
    'perspective': '',
    'dof': ('SceneVariables { ["enable_dof"] = true }\n'
            'PerspectiveCamera("/camera") { ["dof"] = true, ["dof_aperture"] = 11.0, ["dof_focus_distance"] = 6.2 }\n'),
    'motion': ('SceneVariables { ["enable_motion_blur"] = true, ["motion_steps"] = {-0.25, 0.25} }\n'
               'PerspectiveCamera("/camera") { ["node_xform"] = blur(%s, %s), ["mb_shutter_open"] = -0.25, ["mb_shutter_close"] = 0.25 }\n'
               % (CAMERA, MOVED)),
    'ortho': ('OrthographicCamera("/ortho") { ["node_xform"] = %s, ["film_width_aperture"] = 9.0, ["near"] = 0.01, ["far"] = 1000.0 }\n'
              'SceneVariables { ["camera"] = OrthographicCamera("/ortho") }\n' % CAMERA),
    'spherical': ('SphericalCamera("/sph") { ["node_xform"] = %s, ["min_latitude"] = -50.0, ["max_latitude"] = 50.0, '
                  '["min_longitude"] = -75.0, ["max_longitude"] = 75.0, ["focal"] = 30.0, ["near"] = 0.01, ["far"] = 1000.0 }\n'
                  'SceneVariables { ["camera"] = SphericalCamera("/sph") }\n' % CAMERA),
    'fisheye': ('FisheyeCamera("/fish") { ["node_xform"] = %s, ["mapping"] = 1, ["format"] = 1, ["zoom"] = 1.0, ["fov"] = 140.0, '
                '["near"] = 0.01, ["far"] = 1000.0 }\n'
                'SceneVariables { ["camera"] = FisheyeCamera("/fish") }\n' % CAMERA),
    'dome': ('DomeMaster3DCamera("/dome") { ["node_xform"] = %s, ["FOV_vertical_angle"] = 160.0, ["FOV_horizontal_angle"] = 160.0, '
             '["stereo_view"] = 0, ["near"] = 0.01, ["far"] = 1000.0 }\n'
             'SceneVariables { ["camera"] = DomeMaster3DCamera("/dome") }\n' % CAMERA),
}


def realtime(samples):
    """The kit's realtime frame: XPU2's generations UserData with realtime on, and Rhea's outputs (rdla.rhea_lines)."""
    import types
    if 'PySide2' not in sys.modules:
        qt = types.ModuleType('PySide2')
        qt.QtCore = types.SimpleNamespace(QSettings=None)
        sys.modules['PySide2'] = qt
    from moonray_modo import rdla
    lines = ['UserData("/modo/xpu2/generations") {', '  ["float_key"] = "xpu2_generations",',
             '  ["float_values_0"] = {2, 1, %d, 1, 0, 0, 0, 1, 1},' % samples, '}']
    return '\n'.join(lines + rdla.rhea_lines('rhea.exr')) + '\n'


def pfm(path):
    data = path.read_bytes()
    parts = data.split(b'\n', 3)
    w, h = map(int, parts[1].split())
    a = array.array('f')
    a.frombytes(parts[3][:w * h * 12])
    if float(parts[2]) > 0:
        a.byteswap()
    out = array.array('f', [1.0]) * (w * h * 4)
    for i in range(w * h):
        out[4 * i:4 * i + 3] = a[3 * i:3 * i + 3]
    return out, w, h


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--exe', type=Path, required=True)
    p.add_argument('--scene', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--cases', default=','.join(CASES))
    p.add_argument('--samples', type=int, default=32)
    p.add_argument('--reference', type=int, default=1024)
    p.add_argument('--mode', default='1')
    p.add_argument('--optix-cache', type=Path)
    p.add_argument('--shader-marks', type=Path)
    p.add_argument('--rhea-env', action='append', default=[], help="KEY=VALUE for Rhea's runs (the session's investigation switches)")
    p.add_argument('--oiiotool', type=Path, default=HERE.parents[1] / 'toolchain/msys64/ucrt64/bin/oiiotool.exe')
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    if a.optix_cache:
        env['OPTIX_CACHE_PATH'] = str(a.optix_cache.resolve())
    if a.shader_marks:
        env['XPU2_SHADER_MARKS'] = str(a.shader_marks.resolve())
    (a.output / 'realtime.rdla').write_text(realtime(a.samples), encoding='utf-8')
    (a.output / 'reference.rdla').write_text(realtime(a.reference), encoding='utf-8')
    report = {}
    for case in a.cases.split(','):
        folder = a.output / case
        folder.mkdir()
        camera = folder / 'camera.rdla'
        camera.write_text(CASES[case], encoding='utf-8')
        runs = {}
        for name, engine, frame in (('rhea', 'rhea', 'realtime.rdla'), ('xpu2', 'xpu2', 'realtime.rdla'), ('reference', 'xpu2', 'reference.rdla')):
            run = folder / name
            run.mkdir()
            command = [str(a.exe), 'render', '-in', str(a.scene.resolve()), '-in', str(camera.resolve()), '-in', str((a.output / frame).resolve()),
                       '-out', 'beauty.exr', '--mode', a.mode]
            extra = dict(kv.split('=', 1) for kv in a.rhea_env) if name == 'rhea' else {}
            done = subprocess.run(command, cwd=run, env=dict(env, XPU2_SESSION_RT_ENGINE=engine, **extra), capture_output=True, text=True, timeout=1200)
            (run / 'session.log').write_text(done.stdout + done.stderr, encoding='utf-8')
            info = {'exit': done.returncode}
            log = done.stdout
            for line in log.splitlines():
                if 'realtime by Rhea:' in line:
                    m = re.search(r'(\d+) frames in ([\d.]+) s, (\d+) probes, (\d+)% of the picture verified, phase 1 in (\d+)%', line)
                    if m:
                        info.update(frames=int(m.group(1)), seconds=float(m.group(2)), probes=int(m.group(3)), verified=int(m.group(4)), phase1=int(m.group(5)))
                if "frames by XPU2 alone, not Rhea's" in line:
                    info['xpu2_because'] = line.split("not Rhea's: ", 1)[-1]
                m = re.search(r'MoonRay XPU2: finished in ([\d.]+) s', line)
                if m:
                    info['finished'] = float(m.group(1))
                if 'FALLBACK' in line:
                    info['fallback'] = line
            if (run / 'beauty.exr').exists():
                subprocess.run([str(a.oiiotool), str(run / 'beauty.exr'), '--ch', 'R,G,B', '-o', str(run / 'beauty.pfm')], capture_output=True)
            runs[name] = info
        if all((folder / n / 'beauty.pfm').exists() for n in ('rhea', 'xpu2', 'reference')):
            ref, w, h = pfm(folder / 'reference' / 'beauty.pfm')
            for name in ('rhea', 'xpu2'):
                img, _, _ = pfm(folder / name / 'beauty.pfm')
                e = errors(img, ref, w, h)
                runs[name].update(relative_mse=e['relative_mse'], block_error=e['block_error'], mean_ratio=e['mean_ratio'])
        report[case] = runs
        r, x = runs.get('rhea', {}), runs.get('xpu2', {})
        print('%-11s rhea %s  xpu2 %s' % (case,
              ('relMSE %.2e block %.2e ratio %.4f | %ss, %s probes, verified %s%%, phase 1 %s%%' % (
                  r.get('relative_mse', 0), r.get('block_error', 0), r.get('mean_ratio', 0), r.get('finished'), r.get('probes'), r.get('verified'), r.get('phase1'))
               if 'relative_mse' in r else 'no picture: %s' % (r.get('xpu2_because') or r.get('fallback') or r.get('exit'))),
              ('relMSE %.2e block %.2e ratio %.4f | %ss' % (x.get('relative_mse', 0), x.get('block_error', 0), x.get('mean_ratio', 0), x.get('finished'))
               if 'relative_mse' in x else 'no picture')), flush=True)
        if r.get('xpu2_because'):
            print('            Rhea left it to XPU2: %s' % r['xpu2_because'], flush=True)
    (a.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
