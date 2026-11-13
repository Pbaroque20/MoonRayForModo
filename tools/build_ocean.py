"""Build modo_ocean.dll, which makes an ocean tile as moonray_modo/ocean.py does (Tessendorf's FFT ocean), many times
faster and up to 1024 across. The kit loads it into Modo's own Python (ctypes, ocean.library) from its bin folder.

Usage: build_ocean.py [kit bin folder to copy it into ...]
The compiler is the toolchain's own; the library needs nothing beyond the C++ library, which is linked into it."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UCRT = ROOT / 'toolchain/msys64/ucrt64'
SOURCE = ROOT / 'native-port/modo_ocean.cpp'
TARGET = ROOT / 'build/native-avx/bin/modo_ocean.dll'


def main():
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    # No fused multiply-add: the numbers come out as Python's do, to the float the images keep. Static runtime: the
    # library loads in Modo with nothing of the toolchain beside it.
    command = [str(UCRT / 'bin/g++.exe'), '-O2', '-std=c++17', '-ffp-contract=off', '-Wall', '-shared', str(SOURCE), '-o', str(TARGET),
               '-static', '-static-libgcc', '-static-libstdc++']
    env = dict(os.environ, PATH=str(UCRT / 'bin') + os.pathsep + os.environ.get('PATH', ''))
    done = subprocess.run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if done.returncode:
        raise SystemExit(done.stdout.decode(errors='replace')[-4000:])
    print('Built', TARGET)
    for folder in sys.argv[1:]:
        shutil.copy2(TARGET, Path(folder) / TARGET.name)
        print('Copied into', folder)


if __name__ == '__main__':
    main()
