"""MoonLightIPR's light passes gathered beside the beauty from the start: check_moonlightipr_session.py's scene rendered,
then Diffuse, Glossy, Emission, Background and Beauty chosen, each of which must come at once as another picture, with
no render begun again. The four passes must add up to the beauty. Then the beauty's speed (every AOV gathered with it)
against another session (a build of scene form P, which gathers none) where one is given.
check_moonlightipr_passes.py [earlier moonlightipr folder]"""
import pathlib
import struct
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
import check_moonlightipr_session as fixture
from moonray_modo import moonlightipr_scene

W, H = fixture.WIDTH, fixture.HEIGHT
folder = ROOT / 'test-results/moonlightipr-passes'
folder.mkdir(parents=True, exist_ok=True)


def lines(session, until, seconds=120):
    """Events until one satisfies until(line); the pixels of the last frame sent, and what came."""
    seen, pixels, ends = [], None, time.perf_counter() + seconds
    for raw in session.process.stdout:
        line = raw.decode('utf-8', errors='replace').strip()
        if line.startswith('@@MODO_SHARED '):
            _, key, width, height, pixels = fixture.receive(line, session.process.pid)
            seen.append('frame ' + key)
        elif line.startswith('@@MODO_SESSION '):
            seen.append(' '.join(line.split()[1:4]))
        if until(line) or time.perf_counter() > ends:
            return pixels, seen
    raise RuntimeError('Session exited early')


def command(session, text):
    session.process.stdin.write((text + '\n').encode())
    session.process.stdin.flush()


def unpack(pixels):
    return struct.unpack('<%df' % (W * H * 3), pixels)


def render(session, samples, older=False):
    payload, keys, _ = moonlightipr_scene.pack(fixture.snapshot(), W, H, environment=0, known=set(), samples=samples)
    if older:
        # For a session of form P: the scene without its roughness clamp (form Q's one number after the sample clamp,
        # the clamp's bounce and the subsurface scatterings).
        assert payload[:4] == b'MLSQ'
        payload = b'MLSP' + payload[4:48] + payload[52:]
    started = time.perf_counter()
    session.send(payload)
    pixels, _ = lines(session, lambda line: line.startswith('@@MODO_SESSION DONE'))
    return pixels, time.perf_counter() - started


session = fixture.Session(folder)
try:
    command(session, 'view 0 beauty')
    beauty, seconds = render(session, 256)
    print('beauty: 256 samples in %.2f s' % seconds)
    passes = {}
    for n, name in ((1, 'diffuse'), (2, 'glossy'), (3, 'emission'), (4, 'background'), (0, 'beauty')):
        started = time.perf_counter()
        command(session, 'aov %d %s' % (n, name))
        pixels, seen = lines(session, lambda line: line.startswith('@@MODO_SHARED '))
        took = time.perf_counter() - started
        again = [s for s in seen if s.startswith('SAMPLES') or s.startswith('DONE')]
        print('%-10s came in %.3f s; %s' % (name, took, 'no render begun again' if not any('DONE' in s for s in again) else 'RENDERED AGAIN'))
        passes[name] = pixels
    total = [sum(v) for v in zip(*(unpack(passes[k]) for k in ('diffuse', 'glossy', 'emission', 'background')))]
    whole = unpack(passes['beauty'])
    off = [abs(a - b) for a, b in zip(total, whole)]
    print('passes summed against the beauty: mean %.6f, largest %.6f; beauty mean %.4f' % (sum(off) / len(off), max(off), sum(whole) / len(whole)))
    for k in ('diffuse', 'glossy', 'emission', 'background'):
        values = unpack(passes[k])
        print('   %-10s mean %.4f' % (k, sum(values) / len(values)))
finally:
    command(session, 'quit')

if len(sys.argv) > 1:
    # The beauty alone, no AOVs, against an earlier session: the same scene, the same samples, three times each.
    earlier = pathlib.Path(sys.argv[1])
    timings = {}
    for label, exe, ptx in (('this build', fixture.BUILD / 'bin/moonlightipr_session.exe', fixture.BUILD / 'shaders/MoonLightIPRKernel.ptx'),
                            ('earlier', earlier / 'moonlightipr_session.exe', earlier / 'MoonLightIPRKernel.ptx')) * 2:
        s = fixture.Session(folder)
        s.process.kill()
        env = dict(fixture.os.environ)
        env['PATH'] = fixture.os.pathsep.join([str(ROOT / 'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/bin'), env.get('PATH', '')])
        s.process = subprocess.Popen([str(exe), str(ptx)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            command(s, 'view 0 beauty')
            render(s, 64, label == 'earlier')
            for _ in range(3):
                _, seconds = render(s, 1024, label == 'earlier')
                timings.setdefault(label, []).append(seconds)
        finally:
            command(s, 'quit')
    for label, values in timings.items():
        print('%-10s 1024 samples: best %.3f s of %s' % (label, min(values), ' '.join('%.3f' % v for v in values)))
