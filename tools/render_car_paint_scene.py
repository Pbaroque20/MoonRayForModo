"""Renders make_car_paint_scene.py's scene outside Modo with the built kit, in MoonRay, XPU2 and MoonLightIPR. Writes
test-results/car-paint-scene/<renderer>.png. A renderer named as an argument alone: moonray, xpu2, moonlightipr."""
import os
import pickle
import struct
import subprocess
import sys
import time
from pathlib import Path
os.environ['MOONRAY_MODO_PREFERENCES'] = 'TestPreview'
for folder in (r'C:\Program Files\Modo16.1v9\modo', r'C:\Program Files\Modo16.1v9\modo\resrc\python3kit\extra64'):
    os.add_dll_directory(folder)
ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / 'dist/personal-kit/Luxology/Kits/MoonRayForModo'
sys.path[:0] = [str(ROOT / 'tools'), str(KIT / 'python')]
runtime = KIT / 'runtime'
os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
from PySide2 import QtCore
app = QtCore.QCoreApplication([])
from moonray_modo import native, options, persistent, rdla
from moonray_modo.preferences import Preferences
out = ROOT / 'test-results/car-paint-scene'
env = native.environment(runtime)
W, H = 960, 540
which = sys.argv[1:] or ['moonray', 'xpu2', 'moonlightipr']
scene = pickle.loads((out / 'snapshot.pickle').read_bytes())
scene.update(width=W, height=H, aovs=['alpha'], custom_aovs=[], preview_buffer='beauty')
scene['render_settings'] = dict(scene.get('render_settings') or {}, sampling_mode=0, pixel_samples=8)
scene['render_settings'] = options.render_values(scene['render_settings'])


def png(values, w, h, name):
    pfm = out / (name + '.pfm')
    pfm.write_bytes(('PF\n%d %d\n-1.0\n' % (w, h)).encode() + struct.pack('<%df' % (w * h * 3), *values))
    subprocess.run([str(runtime / 'oiiotool.exe'), str(pfm), '--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o', str(out / (name + '.png'))], env=env, capture_output=True)


exr = out / 'moonray.exr'
text = rdla.scene_text(scene, W, H, 8, 0, str(exr))
if 'moonray' in which:
    path = out / 'moonray.rdla'
    path.write_text(text, encoding='utf-8')
    started = time.time()
    done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(path, exr, 0, 'vectorized'), env=env, cwd=str(out), capture_output=True, text=True)
    subprocess.run([str(runtime / 'oiiotool.exe'), str(exr), '--ch', 'R,G,B', '--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o', str(out / 'moonray.png')], env=env, capture_output=True)
    print('MoonRay rc', done.returncode, '%.0f s' % (time.time() - started), [l.strip()[:130] for l in done.stdout.splitlines() if 'Error' in l or 'Warn' in l][:3], flush=True)
if 'xpu2' in which:
    store = Preferences().store
    store.setValue('xpu2/renderer', 'xpu2')
    store.sync()
    session = persistent.Session()
    last, finished = {}, []
    session.memory_image.connect(lambda p: last.__setitem__(p[1], p))
    session.ready.connect(lambda g: finished.append(g))
    session.failed.connect(lambda m: (print('  failed', m[:300]), finished.append(-1)))
    started = time.time()
    session.submit(text, runtime, 0, 'xpu', 1)
    deadline = time.time() + 200
    while not finished and time.time() < deadline:
        app.processEvents()
        time.sleep(.02)
    print('XPU2 active', getattr(session, 'xpu2_active', None), 'refused', getattr(session, 'xpu2_refused', None), '%.0f s' % (time.time() - started), flush=True)
    p = last.get('beauty')
    session.close()
    for _ in range(50):
        app.processEvents()
        time.sleep(.02)
    store.remove('xpu2/renderer')
    if p:
        png(struct.unpack('<%df' % (p[2] * p[3] * 3), p[4]), p[2], p[3], 'xpu2')
if 'moonlightipr' in which:
    import compare_moonlightipr as compare
    compare.WIDTH, compare.HEIGHT = W, H
    compare.fixture.WIDTH, compare.fixture.HEIGHT = W, H
    light = compare.fixture.Session(out)
    light.runtime = runtime
    try:
        preview, warnings = compare.moonlightipr(dict(scene, _environment=0), light, 'car')
        print('MoonLightIPR', warnings, flush=True)
        png(preview, W, H, 'moonlightipr')
        light.process.stdin.write(b'quit\n')
        light.process.stdin.flush()
        light.process.wait(timeout=10)
    finally:
        if light.process.poll() is None:
            light.process.kill()
