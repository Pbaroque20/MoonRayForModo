"""Obtain a native call stack from this project's renderer test process only."""
from pathlib import Path
import os
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import native
runtime = root / 'runtime/native-avx'
results = root / 'test-results/native-render'
environment = native.environment(runtime)
environment['PATH'] = str(root / 'toolchain/msys64/ucrt64/bin') + os.pathsep + environment['PATH']
command = [str(root / 'toolchain/msys64/ucrt64/bin/gdb.exe'), '-batch',
           '-ex', 'set pagination off', '-ex', 'run', '-ex', 'x/12i $pc-24',
           '-ex', 'info registers', '-ex', 'thread apply all bt 18',
           '--args', str(runtime / 'moonray.exe')]
command += native.arguments(results / 'triangle.rdla', results / 'debug-render.png', 1,
                            'vectorized' if '--vectorized' in sys.argv else 'scalar')
with (results / 'gdb.log').open('w', encoding='utf-8') as log:
    process = subprocess.run(command, env=environment, cwd=results, stdout=log,
                             stderr=subprocess.STDOUT, timeout=60,
                             creationflags=subprocess.CREATE_NO_WINDOW)
print((results / 'gdb.log').read_text(encoding='utf-8', errors='replace')[-14000:])
