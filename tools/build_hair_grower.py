"""Build modo_hair_grow.exe, which grows hair from guides as moonray_modo/hair.py does, many times faster.

Usage: build_hair_grower.py [runtime folder to copy it into ...]
The compiler is the toolchain's own; the program needs nothing beyond the C++ library, which is linked into it."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UCRT = ROOT / 'toolchain/msys64/ucrt64'
SOURCE = ROOT / 'native-port/modo_hair_grow.cpp'
TARGET = ROOT / 'build/native-avx/bin/modo_hair_grow.exe'


def main():
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    # No -ffast-math and no fused multiply-add: the numbers must come out as Python's do.
    command = [str(UCRT / 'bin/g++.exe'), '-O2', '-std=c++17', '-ffp-contract=off', '-Wall', str(SOURCE), '-o', str(TARGET), '-static']
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
