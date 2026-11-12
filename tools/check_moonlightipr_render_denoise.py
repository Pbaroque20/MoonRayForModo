"""MoonLightIPR's denoised beauty after a Render (RT off), from the session alone: check_moonlightipr_session.py's scene
packed as a Render packs it (every sample, flat out, not denoised as it goes), then (a) rendered to its end and (b)
paused partway, as Stop pauses it; each time the denoised view asked for ('view 0 denoised'). The picture that comes
must come, and be smoother than the beauty: the mean difference between neighbouring pixels says how noisy each is.
check_moonlightipr_render_denoise.py"""
import array
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
import check_moonlightipr_session as fixture
from moonray_modo import moonlightipr_scene

W, H = fixture.WIDTH, fixture.HEIGHT
folder = ROOT / 'test-results/moonlightipr-render-denoise'
folder.mkdir(parents=True, exist_ok=True)


def roughness(pixels):
    """The mean difference between each pixel and the one to its right: noise, mostly."""
    values = array.array('f')
    values.frombytes(bytes(pixels)[:W * H * 12])
    total = 0.0
    for y in range(0, H, 2):
        row = values[y * W * 3:(y + 1) * W * 3]
        total += sum(abs(row[i] - row[i + 3]) for i in range(0, (W - 1) * 3))
    return total / ((H // 2) * (W - 1) * 3)


def events(session, until, seconds=120):
    seen, last, ends = [], None, time.monotonic() + seconds
    for raw in session.process.stdout:
        line = raw.decode('utf-8', errors='replace').strip()
        if line.startswith('@@MODO_SHARED '):
            _, key, width, height, pixels = fixture.receive(line, session.process.pid)
            last = pixels
            seen.append('frame ' + key)
        elif line.startswith('@@MODO_SESSION '):
            seen.append(' '.join(line.split()[1:4]))
        if until(line) or time.monotonic() > ends:
            return last, seen
    raise RuntimeError('session ended early')


def ask(session, text):
    session.process.stdin.write((text + '\n').encode())
    session.process.stdin.flush()


def case(label, pause_after):
    session = fixture.Session(folder)
    try:
        ask(session, 'view 0 beauty')
        scene = dict(fixture.snapshot(), _flat_out=True)
        payload, _, _ = moonlightipr_scene.pack(scene, W, H, environment=0, known=set(), samples=2048, denoise=False)
        path = folder / ('%s.mls' % label)
        path.write_bytes(payload)
        ask(session, 'scene 1 %s' % path)
        if pause_after is None:
            beauty, seen = events(session, lambda line: line.startswith('@@MODO_SESSION DONE'))
        else:
            started = time.monotonic()
            beauty, seen = events(session, lambda line: time.monotonic() - started > pause_after and line.startswith('@@MODO_SHARED '))
            ask(session, 'pause')
            time.sleep(1.0)
        started = time.monotonic()
        ask(session, 'view 0 denoised')
        denoised, seen = events(session, lambda line: line.startswith('@@MODO_SHARED '), seconds=30)
        took = time.monotonic() - started
        if denoised is None or denoised is beauty:
            print('%-10s no denoised picture came (%s)' % (label, ', '.join(seen[-4:])))
            return
        print('%-10s denoised picture in %.2f s; noise: beauty %.4f, denoised %.4f' % (label, took, roughness(beauty), roughness(denoised)))
    finally:
        ask(session, 'quit')
        session.process.wait(timeout=30)


case('finished', None)
case('paused', 1.5)
