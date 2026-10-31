"""A scene read by probe_cl_snapshot_scene.py, rendered outside Modo with the built kit in MoonRay and MoonLightIPR at the same size.
compare_scene_renderers.py <folder> [width height samples]: writes <folder>/moonray.png and moonlightipr.png."""
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
from moonray_modo import native, options, rdla

out = Path(sys.argv[1])
W, H, SAMPLES = (int(v) for v in (sys.argv[2:5] or (640, 360, 16)))
env = native.environment(runtime)
scene = pickle.loads((out / 'snapshot.pickle').read_bytes())
scene.update(width=W, height=H, aovs=['alpha'], custom_aovs=[], preview_buffer='beauty')
scene['render_settings'] = options.render_values(dict(scene.get('render_settings') or {}, sampling_mode=0, pixel_samples=SAMPLES))

exr = out / 'moonray.exr'
path = out / 'moonray.rdla'
path.write_text(rdla.scene_text(scene, W, H, SAMPLES, 0, str(exr)), encoding='utf-8')
started = time.time()
done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(path, exr, 0, 'vectorized'), env=env, cwd=str(out), capture_output=True, text=True)
subprocess.run([str(runtime / 'oiiotool.exe'), str(exr), '--ch', 'R,G,B', '--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o', str(out / 'moonray.png')], env=env, capture_output=True)
print('MoonRay rc', done.returncode, '%.0f s' % (time.time() - started), flush=True)

import compare_moonlightipr as compare
compare.WIDTH, compare.HEIGHT = W, H
compare.fixture.WIDTH, compare.fixture.HEIGHT = W, H
light = compare.fixture.Session(out)
light.runtime = runtime
try:
    started = time.time()
    preview, warnings = compare.moonlightipr(dict(scene, _environment=0), light, 'scene')
    print('MoonLightIPR', warnings, '%.0f s' % (time.time() - started), flush=True)
    pfm = out / 'moonlightipr.pfm'
    pfm.write_bytes(('PF\n%d %d\n-1.0\n' % (W, H)).encode() + struct.pack('<%df' % (W * H * 3), *preview))
    subprocess.run([str(runtime / 'oiiotool.exe'), str(pfm), '--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o', str(out / 'moonlightipr.png')], env=env, capture_output=True)
    light.process.stdin.write(b'quit\n')
    light.process.stdin.flush()
    light.process.wait(timeout=10)
finally:
    if light.process.poll() is None:
        light.process.kill()
