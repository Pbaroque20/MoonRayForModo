"""Build modo_abc_reader.exe, which reads an Alembic file's meshes (their points and velocities) for motion blur.

Usage: build_abc_reader.py [runtime folder to copy it into ...]
The compiler and Alembic are the toolchain's own (MSYS2's mingw-w64-ucrt-x86_64-alembic, installed 2026-11-08), linked
in whole (Ogawa files only: no HDF5), so the reader needs only the Imath library the runtime already holds."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UCRT = ROOT / 'toolchain/msys64/ucrt64'
SOURCE = ROOT / 'native-port/modo_abc_reader.cpp'
TARGET = ROOT / 'build/native-avx/bin/modo_abc_reader.exe'


def main():
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    command = [str(UCRT / 'bin/g++.exe'), '-O2', '-std=c++17', '-w', str(SOURCE), '-o', str(TARGET),
               str(UCRT / 'lib/libAlembic.a'), '-lImath', '-static-libgcc', '-static-libstdc++',
               '-Wl,-Bstatic', '-lwinpthread', '-Wl,-Bdynamic']
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
