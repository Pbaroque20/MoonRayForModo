"""run_watched.py <session N> <scene folder> <tag> [--env K=V ...] [--timeout s] [--stop-after-ready s]: the XPU2 harness on
<scene folder>/preview.rdla + preview.rdlb with the kit's Source Override env, the GPU's memory in use sampled every
second meanwhile (nvidia-smi) and the process's own peak working set; writes <scene folder>/<tag>/ (protocol.log,
report.json) and prints the protocol's XPU2 lines with the memory peaks."""
import argparse
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

TR = Path(r'C:\Users\Raphael Tobar\MoonRayForModo-xpu2\test-results')
HARNESS = Path(r'C:\Users\Raphael Tobar\MoonRayForModo-xpu2-async\xpu2\interactive\session_harness.py')
KIT_ENV = ['MOONRAY_MODO_%s=1' % k for k in ('TOON_TERMINATOR', 'TOON_ALBEDO', 'DENOISE_CLEAN_GUIDES', 'CRYPTO_VOLUMES', 'FOG_ALPHA', 'CRYPTO_ONCE',
                                            'USD_SPECULAR', 'OPAQUE_ALPHA', 'TRANSMISSION_ROUGHNESS')]
p = argparse.ArgumentParser()
p.add_argument('session')
p.add_argument('folder', type=Path)
p.add_argument('tag')
p.add_argument('--env', action='append', default=[])
p.add_argument('--timeout', type=int, default=900)
p.add_argument('--extra', default='', help='an overlay .rdla sent with the scene')
a = p.parse_args()
if 'modo.exe' in subprocess.run(['tasklist'], capture_output=True, text=True).stdout.lower():
    sys.exit('Modo is running: no GPU tests while the user tests in Modo')
out = a.folder / a.tag
exe = TR / ('xpu2-session-%s' % a.session) / 'runtime-xpu2' / 'moonray_xpu2.exe'
args = [sys.executable, str(HARNESS), '--exe', str(exe), '--scene', str(a.folder / 'preview.rdla'), '--scene', str(a.folder / 'preview.rdlb')]
if a.extra:
    args += ['--scene', a.extra]
args += ['--output', str(out), '--threads', '12', '--timeout', str(a.timeout)]
for v in KIT_ENV + a.env:
    args += ['--env', v]
samples = []
done = threading.Event()


def sample():
    while not done.is_set():
        r = subprocess.run(['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'], capture_output=True, text=True)
        try:
            samples.append((time.time(), int(r.stdout.strip().splitlines()[0])))
        except (ValueError, IndexError):
            pass
        done.wait(1.0)


base = subprocess.run(['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'], capture_output=True, text=True).stdout.strip()
watcher = threading.Thread(target=sample, daemon=True)
began = time.time()
watcher.start()
r = subprocess.run(args, capture_output=True, text=True)
done.set()
watcher.join()
print('harness:', r.stdout.strip()[-400:], r.stderr.strip()[-400:], 'in %.1f s' % (time.time() - began))
log = (out / 'protocol.log').read_text(encoding='utf-8', errors='replace').splitlines() if (out / 'protocol.log').exists() else []
for line in log:
    s = line.strip()
    if any(k in s for k in ('XPU2', 'xpu2', 'FALLBACK', 'APPLIED', 'DONE', 'budget', 'GPU')):
        print('  ', s[:400])
if samples:
    peak = max(samples, key=lambda x: x[1])
    print('GPU memory in use: %s MiB before, peak %d MiB at %.0f s' % (base, peak[1], peak[0] - began))
