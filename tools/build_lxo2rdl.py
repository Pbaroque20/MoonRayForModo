"""Build lxo2rdl.exe, the kit's command-line LXO to RDL converter (native-port/lxo2rdl.cpp), which the release puts in the
kit's bin folder beside scripts/export_moonray.py's kit.

Usage: build_lxo2rdl.py [kit bin folder to copy it into ...]
The compiler is the toolchain's own; the program is linked statically, so that it runs with nothing beside it."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UCRT = ROOT / 'toolchain/msys64/ucrt64'
SOURCE = ROOT / 'native-port/lxo2rdl.cpp'
TARGET = ROOT / 'build/native-avx/bin/lxo2rdl.exe'


def main():
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    command = [str(UCRT / 'bin/g++.exe'), '-O2', '-std=c++17', '-Wall', '-municode', str(SOURCE), '-o', str(TARGET),
               '-static', '-static-libgcc', '-static-libstdc++']
    env = dict(os.environ, PATH=str(UCRT / 'bin') + os.pathsep + os.environ.get('PATH', ''))
    done = subprocess.run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if done.returncode:
        raise SystemExit(done.stdout.decode(errors='replace')[-4000:])
    if done.stdout.strip():
        print(done.stdout.decode(errors='replace')[-4000:])
    print('Built', TARGET)
    for folder in sys.argv[1:]:
        shutil.copy2(TARGET, Path(folder) / TARGET.name)
        print('Copied into', folder)


if __name__ == '__main__':
    main()
