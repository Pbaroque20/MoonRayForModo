"""Render feature test scenes with XPU2 and MoonRay through the session harness, and compare.

feature_compare.py <folder of case .rdla with OUTPUT placeholders> <xpu2 exe> <cases...> [--samples N] [--mode xpu2mode] [--moonray-mode vectorized]
Each case: XPU2, MoonRay (frame 0) and MoonRay (frame 1, the noise floor). Prints block error and mean ratio of XPU2
and of MoonRay frame 1 against MoonRay frame 0, and writes <case>-compare.png (XPU2 | MoonRay | difference x8)."""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import runq

S = Path(__file__).resolve().parent
HARNESS = Path(r'C:\Users\Raphael Tobar\MoonRayForModo-xpu2-async\xpu2\interactive\session_harness.py')
RT = Path(r'C:\Users\Raphael Tobar\AppData\Roaming\Luxology\Kits\MoonRayForModo\runtime')
MOONRAY = RT / 'moonray.exe'
TOOL = RT / 'oiiotool.exe'

p = argparse.ArgumentParser()
p.add_argument('folder', type=Path)
p.add_argument('xpu2', type=Path)
p.add_argument('cases', nargs='+')
p.add_argument('--samples', type=int, default=16)
p.add_argument('--mode', default='0')
p.add_argument('--moonray-mode', default='vectorized')
p.add_argument('--threads', type=int, default=0)
p.add_argument('--floor', choices=('aux', 'frame'), default='aux')
a = p.parse_args()
folder = a.folder.resolve()
results = {}
for case in a.cases:
    text = (folder / (case + '.rdla')).read_text(encoding='utf-8')
    text = re.sub(r'\["pixel_samples"\]=\d+', '["pixel_samples"]=%d' % a.samples, text)
    runs = {'xpu2': (a.xpu2, '0', 'xpu'), 'moonray': (MOONRAY, '0', a.moonray_mode), 'moonray1': (MOONRAY, '1', a.moonray_mode)}
    if a.floor == 'aux':
        del runs['moonray1']
    for name, (exe, frame, mode) in runs.items():
        out = folder / ('%s-%s.exr' % (case, name))
        scene = folder / ('%s-%s.rdla' % (case, name))
        scene_text = text.replace('OUTPUT', out.as_posix()).replace('["frame"]=0', '["frame"]=%s' % frame)
        if name == 'moonray' and a.floor == 'aux':
            # MoonRay's odd-sample half image beside the beauty (its adaptive sampler's beauty aux).
            scene_text = scene_text.replace('RenderOutput("/beauty") {', 'RenderOutput("/x2aux") { ["file_name"]="%s", ["result"]=12 }\nRenderOutput("/beauty") {' % out.as_posix(), 1)
        scene.write_text(scene_text, encoding='utf-8')
        if out.exists():
            out.unlink()
        # A MoonRay reference already rendered from the same scene, frame, mode and build is reused.
        key = runq.reference_key(scene_text, out, frame, mode, exe) if name != 'xpu2' else None
        if key and runq.cached(key, out):
            results.setdefault(case, {})[name + '_seconds'] = 'cached'
            continue
        log = folder / ('%s-%s-harness' % (case, name))
        if log.exists():
            import shutil
            shutil.rmtree(log)
        args = [sys.executable, str(HARNESS), '--exe', str(exe), '--scene', str(scene), '--output', str(log), '--threads', str(a.threads or runq.threads()),
                '--mode', mode, '--timeout', '1800']
        if name == 'xpu2':
            args += ['--env', 'XPU2_SESSION_MODE=' + a.mode]
        with runq.slot():
            r = subprocess.run(args, capture_output=True, text=True)
        if key:
            runq.store(key, out)
        rep = json.loads((log / 'report.json').read_text()) if (log / 'report.json').exists() else {}
        if rep.get('fallback'):
            results.setdefault(case, {})['fallback'] = rep['fallback']
        results.setdefault(case, {})[name + '_seconds'] = rep.get('seconds')
    xo, mo, m1 = (folder / ('%s-%s.exr' % (case, n)) for n in ('xpu2', 'moonray', 'moonray1'))
    if a.floor == 'aux' and mo.exists():
        # A second frame's statistics from the one render R and its odd half H: R + sqrt(2) (R - H) differs from R as
        # an independent render does (the halves' difference has four times a render's variance).
        env = {'PATH': str(RT), 'SYSTEMROOT': r'C:\Windows'}
        r_rgb, h_rgb = folder / ('%s-r.exr' % case), folder / ('%s-h.exr' % case)
        subprocess.run([str(TOOL), str(mo), '--ch', 'R,G,B', '-o', str(r_rgb)], capture_output=True, env=env)
        subprocess.run([str(TOOL), str(mo), '--ch', 'R=__beautyAux__.R,G=__beautyAux__.G,B=__beautyAux__.B', '-o', str(h_rgb)], capture_output=True, env=env)
        if m1.exists():
            m1.unlink()
        subprocess.run([str(TOOL), str(r_rgb), str(r_rgb), str(h_rgb), '--sub', '--mulc', '1.41421356', '--add', '-o', str(m1)], capture_output=True, env=env)
    if xo.exists() and mo.exists() and m1.exists():
        cmp = subprocess.run([sys.executable, str(S / 'block_cmp.py'), str(TOOL), str(mo), str(xo), str(m1)], capture_output=True, text=True,
                             env={'PATH': str(RT), 'SYSTEMROOT': r'C:\Windows'}).stdout
        results[case]['compare'] = cmp.strip().splitlines()
        png = folder / ('%s-compare.png' % case)
        subprocess.run([str(TOOL), str(xo), '--colorconvert', 'linear', 'sRGB', str(mo), '--colorconvert', 'linear', 'sRGB',
                        str(xo), str(mo), '--sub', '--abs', '--mulc', '8', '--colorconvert', 'linear', 'sRGB', '--mosaic', '3x1', '-o', str(png)],
                       capture_output=True, env={'PATH': str(RT), 'SYSTEMROOT': r'C:\Windows'})
    print(case, json.dumps(results[case]), flush=True)
(folder / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
