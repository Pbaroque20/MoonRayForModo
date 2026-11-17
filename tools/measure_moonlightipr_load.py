"""How long the installed kit's MoonLightIPR session takes from a packed scene (scene.mls, probe_cl_moonlightipr_pack.py)
to its first picture and its last, run outside Modo, twice in one session (the second scene sent as a new generation
with nothing known, as a preview started again is). measure_moonlightipr_load.py <scene.mls> <out folder>.
Writes <out>/summary.json and prints the times."""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

root = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo.shared_image import receive  # noqa: E402

kit = pathlib.Path(os.environ['APPDATA']) / 'Luxology/Kits/MoonRayForModo'
runtime = kit / 'runtime'
session_dir = runtime / 'moonlightipr'
scene, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
env = dict(os.environ)
env['PATH'] = os.pathsep.join([str(session_dir), str(runtime), env.get('PATH', '')])
env['MOONRAY_MODO_CACHE'] = str(out / 'cache')
exe = session_dir / 'moonlightipr_session.exe'
ptx = session_dir / 'MoonLightIPRKernel.ptx'
began = time.perf_counter()
process = subprocess.Popen([str(exe), str(ptx)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env,
                           creationflags=subprocess.CREATE_NO_WINDOW)
summary = {'started': None, 'runs': []}
log = (out / 'session.log').open('w', encoding='utf-8')


def run(generation):
    copy = out / ('%d.mls' % generation)
    shutil.copyfile(scene, copy)
    sent = time.perf_counter()
    process.stdin.write(('scene %d %s\n' % (generation, copy)).encode())
    process.stdin.flush()
    first = None
    for raw in process.stdout:
        line = raw.decode('utf-8', errors='replace').strip()
        log.write('%.3f %s\n' % (time.perf_counter() - began, line))
        if line.startswith('@@MODO_SHARED '):
            g = receive(line, process.pid)[0]
            if g == generation and first is None:
                first = time.perf_counter()
        elif line.startswith('@@MODO_SESSION '):
            parts = line.split()
            if len(parts) >= 3 and parts[1] in ('DONE', 'FAILED') and int(parts[2]) == generation:
                return {'generation': generation, 'event': parts[1], 'first_picture': round(first - sent, 3) if first else None,
                        'done': round(time.perf_counter() - sent, 3)}
    return {'generation': generation, 'event': 'exited'}


for generation in (1, 2):
    summary['runs'].append(run(generation))
    print(json.dumps(summary['runs'][-1]), flush=True)
try:
    process.stdin.write(b'quit\n')
    process.stdin.flush()
    process.wait(30)
except Exception:
    process.kill()
log.close()
(out / 'summary.json').write_text(json.dumps(summary, indent=1), encoding='utf-8')
