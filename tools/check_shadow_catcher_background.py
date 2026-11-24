"""A matte shadow catcher (a MoonRay Object's Make as Shadow Catcher) in MoonRay, XPU2 and MoonLightIPR, outside Modo.

The kit's own scene for each engine: a ground made a catcher on its Object tab (backplate.catchers gives it the matte
material), a red ball over it, a sun, and a gradient sky the camera sees (or not). The catcher is to show what the
camera would see past it, darkened by the shadows on it times Shadow Strength, with the shadows in its alpha:

- open ground: the sky the camera sees there (the same scene without the ground, 'reference');
- in the ball's shadow: that sky times (1 - alpha), the alpha strength times the shadow;
- the sky hidden from the camera: black, the shadows in alpha, as before.

    python tools/check_shadow_catcher_background.py [--out test-results/shadow-catcher-background]
        [--moonray build/native-renderer-avx/bin] [--runtime runtime/release-0.5.5.1] [--xpu2 <runtime-xpu2 folder>]
        [--engines moonray-vector,moonray-xpu,xpu2,moonlightipr] [--samples 8]

Writes <case>-<engine>.pfm (beauty), -alpha.pfm and .png (beauty | alpha side by side) into the out folder, and
report.json with each engine's numbers and their differences from MoonRay vector."""
import argparse
import json
import math
import os
import pathlib
import shutil
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
sys.path.insert(0, str(ROOT / 'tools'))

W, H = 320, 180
EYE, TARGET = [0.0, 2.0, 8.0], [0.0, 1.2, 0.0]   # the horizon in the upper part of the frame, sky above it
SUN = [-0.5, -0.8, 0.4]
SKY = {'kind': 'grad4', 'name': 'Sky', 'intensity': 1.0, 'zenith': [0.2, 0.4, 0.9], 'sky': [0.6, 0.75, 1.0],
       'ground': [0.3, 0.25, 0.2], 'nadir': [0.1, 0.1, 0.1], 'sky_exponent': 4, 'ground_exponent': 4}
# name: (ground a catcher of this strength, or None for no ground; the camera sees the sky)
CASES = {'reference': (None, True), 'sky': (1.0, True), 'sky_half': (0.5, True), 'hidden': (1.0, False),
         'hidden_half': (0.5, False)}


def look_at(eye, target):
    back = [e - t for e, t in zip(eye, target)]
    length = math.sqrt(sum(v * v for v in back))
    back = [v / length for v in back]
    right = [back[2], 0.0, -back[0]]
    length = math.sqrt(sum(v * v for v in right))
    right = [v / length for v in right]
    up = [back[1] * right[2] - back[2] * right[1], back[2] * right[0] - back[0] * right[2], back[0] * right[1] - back[1] * right[0]]
    return right + [0.0] + up + [0.0] + back + [0.0] + list(eye) + [1.0]


def ball(segments=64, rings=32, radius=0.8, centre=(0.0, 0.8, 0.0)):
    vertices = [[centre[0] + radius * math.sin(math.pi * r / rings) * math.cos(2 * math.pi * s / segments),
                 centre[1] + radius * math.cos(math.pi * r / rings),
                 centre[2] + radius * math.sin(math.pi * r / rings) * math.sin(2 * math.pi * s / segments)]
                for r in range(rings + 1) for s in range(segments)]
    faces = [[r * segments + s, r * segments + (s + 1) % segments, (r + 1) * segments + (s + 1) % segments, (r + 1) * segments + s]
             for r in range(rings) for s in range(segments)]
    return vertices, faces


def scene(case):
    from moonray_modo import backplate
    strength, seen = CASES[case]
    vertices, faces = ball()
    meshes = [{'name': 'Ball', 'identity': 'ball', 'vertices': vertices, 'faces': faces, 'material': 'red'}]
    if strength is not None:
        meshes.insert(0, {'name': 'Ground', 'identity': 'ground', 'vertices': [[-20, 0, -20], [20, 0, -20], [20, 0, 20], [-20, 0, 20]],
                          'faces': [[0, 3, 2, 1]], 'material': 'grey',
                          'geometry_settings': {'shadow_catcher': True, 'shadow_strength': strength}})
    result = {
        'camera': {'matrix': look_at(EYE, TARGET), 'focal_mm': 50.0, 'film_mm': 36.0},
        'materials': {'grey': {'color': [0.5, 0.5, 0.5], 'roughness': 1.0}, 'red': {'color': [0.8, 0.08, 0.06], 'roughness': 0.6}},
        'meshes': meshes,
        'lights': [{'kind': 'DistantLight', 'identity': 'sun', 'name': 'Sun', 'color': [1, 1, 1], 'intensity': 3.0, 'angle': 2.0,
                    'matrix': look_at([0, 0, 0], SUN)}],
        'environments': [dict(SKY, camera=seen)]}
    warnings = []
    backplate.catchers(result, warnings)
    return result


def project(p):
    """Pixel (x across, y up from the bottom row) of a world point."""
    m = look_at(EYE, TARGET)
    right, up, back = m[0:3], m[4:7], m[8:11]
    d = [a - b for a, b in zip(p, EYE)]
    x, y, z = (sum(a * b for a, b in zip(d, axis)) for axis in (right, up, back))
    scale = (W / 2) / (18.0 / 50.0)
    return W / 2 + x / -z * scale, H / 2 + y / -z * scale


def read_pfm(path):
    data = pathlib.Path(path).read_bytes()
    header = data.split(b'\n', 3)
    width, height = map(int, header[1].split())
    channels = 3 if header[0] == b'PF' else 1
    values = struct.unpack(('<' if float(header[2]) < 0 else '>') + '%df' % (width * height * channels), header[3][:width * height * channels * 4])
    if channels == 1:
        values = [v for v in values for _ in range(3)]
    return list(values)


def write_pfm(path, values):
    pathlib.Path(path).write_bytes(('PF\n%d %d\n-1.0\n' % (W, H)).encode() + struct.pack('<%df' % (W * H * 3), *values))


def write_png(path, runtime, beauty, alpha):
    """Beauty | alpha, sRGB, as a PNG (through a PFM the image tool reads)."""
    from moonray_modo import native
    both = []
    for y in range(H):
        row = slice(y * W * 3, (y + 1) * W * 3)
        both += beauty[row] + alpha[row]
    temp = pathlib.Path(path).with_suffix('.side.pfm')
    temp.write_bytes(('PF\n%d %d\n-1.0\n' % (2 * W, H)).encode() + struct.pack('<%df' % (2 * W * H * 3), *both))
    subprocess.run([str(runtime / 'oiiotool.exe'), str(temp), '--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o', str(path)],
                   env=native.environment(runtime), capture_output=True)
    temp.unlink()


def region(values, at, r=3):
    cx, cy = int(at[0]), int(at[1])
    sums, n = [0.0, 0.0, 0.0], 0
    for y in range(cy - r, cy + r + 1):
        for x in range(cx - r, cx + r + 1):
            i = (y * W + x) * 3
            for c in range(3):
                sums[c] += values[i + c]
            n += 1
    return [s / n for s in sums]


def exr_channels(runtime, image, folder, name):
    """Beauty, alpha and Environment background of a MoonRay or XPU2 EXR, as PFM values bottom row first."""
    from moonray_modo import native
    tool = runtime / 'oiiotool.exe'
    info = subprocess.run([str(tool), '--info', '-v', str(image)], env=native.environment(runtime), capture_output=True, text=True).stdout
    names = []
    for line in info.splitlines():
        if 'channel list:' in line:
            names = [c.strip().split(' ')[0] for c in line.split(':', 1)[1].split(',')]
    picked = {}
    beauty = [c for c in ('R', 'G', 'B') if c in names] or [c for c in names if c.startswith('beauty.')][:3]
    background = [c for c in names if c.startswith('environment_background.')][:3]
    alpha = 'A' if 'A' in names else next((c for c in names if c.endswith('.A') or c == 'alpha'), None)
    for key, channels in (('beauty', beauty), ('background', background), ('alpha', [alpha] * 3 if alpha else [])):
        if len(channels) != 3:
            continue
        out = folder / ('%s-%s.pfm' % (name, key))
        subprocess.run([str(tool), str(image), '--ch', ','.join(channels), '--chnames', 'R,G,B', '-d', 'float', '-o', str(out)],
                       env=native.environment(runtime), check=True, capture_output=True)
        picked[key] = read_pfm(out)
    return picked


def render_moonray(case, mode, args, folder):
    from moonray_modo import native, rdla
    name = '%s-moonray-%s' % (case, mode)
    image = folder / (name + '.exr')
    source = folder / (name + '.rdla')
    source.write_text(rdla.scene_text(scene(case), W, H, args.samples, 0.0, str(image)), encoding='utf-8')
    env = native.environment(args.runtime)
    env['PATH'] = str(args.moonray) + ';' + env['PATH']
    done = subprocess.run([str(args.moonray / 'moonray.exe')] + native.arguments(source, image, threads=args.threads, mode=mode),
                          env=env, capture_output=True, text=True, timeout=1800)
    (folder / (name + '.log')).write_text(done.stdout + done.stderr, encoding='utf-8')
    if done.returncode or not image.is_file():
        raise SystemExit('%s failed: %s' % (name, (done.stdout + done.stderr)[-1500:]))
    return exr_channels(args.runtime, image, folder, name)


def render_xpu2(case, args, folder):
    from moonray_modo import native, rdla
    name = '%s-xpu2' % case
    image = folder / (name + '.exr')
    source = folder / (name + '.rdla')
    source.write_text(rdla.scene_text(scene(case), W, H, args.samples, 0.0, str(image)), encoding='utf-8')
    log = folder / (name + '-harness')
    if log.exists():
        shutil.rmtree(log)
    if image.exists():
        image.unlink()
    harness = ROOT / 'xpu2/interactive/session_harness.py'
    done = subprocess.run([sys.executable, str(harness), '--exe', str(args.xpu2 / 'moonray_xpu2.exe'), '--scene', str(source),
                           '--output', str(log), '--threads', str(args.threads), '--timeout', '900',
                           '--env', 'XPU2_SESSION_MODE=' + args.xpu2_mode], capture_output=True, text=True)
    report = json.loads((log / 'report.json').read_text()) if (log / 'report.json').exists() else {}
    if not image.is_file():
        raise SystemExit('%s failed: %s %s' % (name, report, (done.stdout + done.stderr)[-1500:]))
    picked = exr_channels(args.runtime, image, folder, name)
    picked['fallback'] = report.get('fallback')
    return picked


def render_moonlightipr(cases, args, folder):
    import check_moonlightipr_session as cs
    from moonray_modo import moonlightipr_aovs
    os.environ.setdefault('MOONLIGHTIPR_PACE', '0')
    cs.WIDTH, cs.HEIGHT, cs.SAMPLES = W, H, args.moonlightipr_samples
    sessions = folder / 'moonlightipr-session'
    sessions.mkdir(exist_ok=True)
    for stale in sessions.glob('*.mls'):
        stale.unlink()
    session = cs.Session(sessions)
    pictures = {}

    def aov(kind, key):
        session.process.stdin.write(('aov %d %s\n' % (kind, key)).encode())
        session.process.stdin.flush()
        from moonray_modo.shared_image import receive
        for raw in session.process.stdout:
            line = raw.decode('utf-8', errors='replace').strip()
            if line.startswith('@@MODO_SHARED '):
                generation, got, width, height, pixels = receive(line, session.process.pid)
                if generation == session.generation and got == key:
                    return list(struct.unpack('<%df' % (W * H * 3), pixels))
        raise RuntimeError('no %s picture' % key)
    try:
        session.process.stdin.write(b'view 0 beauty\n')
        session.process.stdin.flush()
        for case in cases:
            result = session.submit(scene(case))
            beauty = list(struct.unpack('<%df' % (W * H * 3), result['pixels']))
            alpha = aov(moonlightipr_aovs.kind('alpha'), 'alpha')
            background = aov(moonlightipr_aovs.kind('environment_background'), 'environment_background')
            aov(0, 'beauty')
            pictures[case] = {'beauty': beauty, 'alpha': alpha, 'background': background}
        session.process.stdin.write(b'quit\n')
        session.process.stdin.flush()
        session.process.wait(timeout=30)
    finally:
        if session.process.poll() is None:
            session.process.kill()
    return pictures


def measure(pictures, reference, shadow_at, open_at, sky_at):
    """The numbers of one engine's case: open ground, the shadow, the sky above the ground, each beside the reference's
    (the sky the camera sees there with no ground), and the alpha."""
    beauty, alpha = pictures['beauty'], pictures.get('alpha') or [0.0] * (W * H * 3)
    entry = {}
    for label, at in (('open', open_at), ('shadow', shadow_at), ('sky', sky_at)):
        value, a = region(beauty, at), region(alpha, at)[0]
        entry[label] = [round(v, 4) for v in value]
        entry[label + '_alpha'] = round(a, 4)
        if reference is not None:
            ref = region(reference, at)
            entry[label + '_reference'] = [round(v, 4) for v in ref]
            # beauty / (reference x (1 - alpha)): 1 where the catcher shows the sky darkened as its alpha says
            entry[label + '_ratio'] = [round(v / (r * (1.0 - a)), 4) if r * (1.0 - a) > 1e-6 else None for v, r in zip(value, ref)]
        if pictures.get('background'):
            entry[label + '_background'] = [round(v, 4) for v in region(pictures['background'], at)]
    return entry


def difference(a, b, mask):
    """Mean of |a - b| over the pixels of mask, beside the mean of b there."""
    total, base, n = 0.0, 0.0, 0
    for i in mask:
        for c in range(3):
            total += abs(a[i * 3 + c] - b[i * 3 + c])
            base += abs(b[i * 3 + c])
        n += 3
    return {'mean_abs': round(total / n, 5), 'relative': round(total / base, 4) if base else None}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', type=pathlib.Path, default=ROOT / 'test-results/shadow-catcher-background')
    p.add_argument('--moonray', type=pathlib.Path, default=ROOT / 'build/native-renderer-avx/bin')
    p.add_argument('--runtime', type=pathlib.Path, default=ROOT / 'runtime/release-0.5.5.1')
    p.add_argument('--xpu2', type=pathlib.Path)
    p.add_argument('--xpu2-mode', default='2', help='XPU2_SESSION_MODE: 0 CPU, 1 GPU, 2 both')
    p.add_argument('--engines', default='moonray-vector,moonray-xpu,xpu2,moonlightipr')
    p.add_argument('--cases', default=','.join(CASES))
    p.add_argument('--samples', type=int, default=8)
    p.add_argument('--moonlightipr-samples', type=int, default=1024)
    p.add_argument('--threads', type=int, default=8)
    args = p.parse_args()
    args.runtime = args.runtime.resolve()
    args.moonray = args.moonray.resolve()
    os.environ['MOONRAY_MODO_RUNTIME'] = str(args.runtime)
    from moonray_modo import native
    native.shadow_catcher_runtime = lambda *a, **k: True   # as a runtime with shadow catchers reads the scene
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cases = [c for c in args.cases.split(',') if c]
    if 'reference' not in cases:
        cases.insert(0, 'reference')
    engines = [e for e in args.engines.split(',') if e and (e != 'xpu2' or args.xpu2)]
    t = 0.8 / -SUN[1]
    shadow_at = project([SUN[0] * t, 0.0, SUN[2] * t])
    open_at = project([2.2, 0.0, 2.6])
    sky_at = (W // 2, H - 8)
    # The ground's pixels, for the differences between engines: those below the far edge of the ground's horizon.
    ground_rows = int(project([0.0, 0.0, -20.0])[1]) - 2
    mask = [y * W + x for y in range(2, ground_rows) for x in range(2, W - 2)]
    found = {}
    for engine in engines:
        folder = out / engine
        folder.mkdir(exist_ok=True)
        if engine == 'moonlightipr':
            found[engine] = render_moonlightipr(cases, args, folder)
        else:
            found[engine] = {case: (render_moonray(case, engine.split('-')[1], args, folder) if engine.startswith('moonray')
                                    else render_xpu2(case, args, folder)) for case in cases}
        for case, pictures in found[engine].items():
            write_pfm(out / ('%s-%s.pfm' % (case, engine)), pictures['beauty'])
            if pictures.get('alpha'):
                write_pfm(out / ('%s-%s-alpha.pfm' % (case, engine)), pictures['alpha'])
            write_png(out / ('%s-%s.png' % (case, engine)), args.runtime, pictures['beauty'], pictures.get('alpha') or [0.0] * (W * H * 3))
        print(engine, 'rendered', flush=True)
    report = {'pixels': {'shadow': shadow_at, 'open': open_at, 'sky': sky_at}, 'engines': {}}
    base = engines[0] if engines else None
    for engine in engines:
        r = report['engines'][engine] = {}
        reference = found[engine].get('reference', {}).get('beauty')
        for case in cases:
            pictures = found[engine][case]
            e = r[case] = measure(pictures, reference if case != 'reference' else None, shadow_at, open_at, sky_at)
            if pictures.get('fallback'):
                e['fallback'] = pictures['fallback']
            if engine != base and case in found[base]:
                e['vs_' + base] = {'beauty': difference(pictures['beauty'], found[base][case]['beauty'], mask)}
                if pictures.get('alpha') and found[base][case].get('alpha'):
                    e['vs_' + base]['alpha'] = difference(pictures['alpha'], found[base][case]['alpha'], mask)
            print(engine, case, json.dumps(e), flush=True)
    (out / 'report.json').write_text(json.dumps(report, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
