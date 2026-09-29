"""Compare normal and forced-alignment ISPC function-pointer calls on Windows."""
from pathlib import Path
import os
import subprocess
root = Path(__file__).resolve().parents[1]
tools = root / 'toolchain/msys64/ucrt64/bin'
build = root / 'build/ispc-mask-probe'
build.mkdir(exist_ok=True)
env = dict(os.environ)
env['PATH'] = str(tools) + os.pathsep + env.get('PATH', '')
for mode in ('normal', 'forced'):
    flags = ['--opt=force-aligned-memory'] if mode == 'forced' else []
    subprocess.run([str(tools / 'ispc.exe'), '--target=avx1-i32x8', '-O2', *flags,
        str(root / 'native-port/ispc_mask_probe.ispc'), '-o', str(build / (mode + '.obj')),
        '-h', str(build / 'ispc_mask_probe.h')], env=env, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    subprocess.run([str(tools / 'g++.exe'), '-O2', '-mavx', '-fno-omit-frame-pointer',
        '-I' + str(build), str(root / 'native-port/ispc_mask_probe.cpp'), str(build / (mode + '.obj')),
        '-o', str(build / (mode + '.exe'))], env=env, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    result = subprocess.run([str(build / (mode + '.exe'))], env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    print(mode, hex(result.returncode & 0xffffffff), result.stdout)
