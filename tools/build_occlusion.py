"""Build modo_occlusion.exe, which works out how open the points of a mesh are, as Modo's Occlusion texture measures it (occlusion.py).

Usage: build_vdb_grid.py [runtime folder to copy it into ...]
The compiler and Embree are the toolchain's own; the runtime already holds the Embree library MoonRay uses."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UCRT = ROOT / 'toolchain/msys64/ucrt64'
SOURCE = ROOT / 'native-port/modo_occlusion.cpp'
TARGET = ROOT / 'build/native-avx/bin/modo_occlusion.exe'


def main():
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    command = [str(UCRT / 'bin/g++.exe'), '-O2', '-std=c++17', '-w', str(SOURCE), '-o', str(TARGET), '-lembree4', '-static-libgcc', '-static-libstdc++']
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
