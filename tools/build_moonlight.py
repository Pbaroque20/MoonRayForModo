"""Build the MoonLight GPU preview module and, with --probe, run its standalone check."""
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN = ROOT / 'toolchain/msys64/ucrt64/bin'
BUILD = ROOT / 'build/moonlight'
CUDART = ROOT / 'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/bin'
env = os.environ.copy()
env['PATH'] = os.pathsep.join([str(BIN), str(CUDART), env.get('PATH', '')])
for key in ('PYTHONHOME', 'PYTHONPATH'):
    env.pop(key, None)
BUILD.mkdir(parents=True, exist_ok=True)

def run(args, name):
    with (BUILD / (name + '.log')).open('w', encoding='utf-8') as log:
        log.write(subprocess.list2cmdline([str(x) for x in args]) + '\n')
        log.flush()
        completed = subprocess.run([str(x) for x in args], cwd=ROOT, env=env,
            stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    output = (BUILD / (name + '.log')).read_text(encoding='utf-8', errors='replace')
    errors = [line for line in output.splitlines() if 'error' in line.lower() or 'FAILED:' in line]
    print('\n'.join(errors[:25]) if errors and completed.returncode else output[-3000:], flush=True)
    if completed.returncode:
        raise SystemExit(completed.returncode)

if '--build-only' not in sys.argv or not (BUILD / 'build.ninja').exists():
    run([BIN / 'cmake.exe', '-S', ROOT / 'moonlight', '-B', BUILD, '-G', 'Ninja',
         '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_CXX_COMPILER=' + str(BIN / 'g++.exe'),
         '-DCMAKE_MAKE_PROGRAM=' + str(BIN / 'ninja.exe')], 'configure')
run([BIN / 'cmake.exe', '--build', BUILD, '--target', 'moonlight_probe', 'moonlight_session'], 'compile')
if '--probe' in sys.argv:
    images = BUILD / 'probe'
    images.mkdir(exist_ok=True)
    run([BUILD / 'bin/moonlight_probe.exe', BUILD / 'shaders/MoonLightKernel.ptx', images], 'probe')
if '--session' in sys.argv:
    run([sys.executable, ROOT / 'tools/check_moonlight_session.py'], 'session')
