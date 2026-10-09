"""Build modo_rdl_import.exe, the scene reader behind the RDL importer, against a finished MoonRay build.

Usage: build_rdl_reader.py [runtime folder to copy it into ...]
Run with the toolchain's own Python or any other; the compiler is the toolchain's. The flags and libraries are the
ones the MoonRay build gives its own scene tools (rdl2_print), read from that build's files."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/native-avx'
UCRT = ROOT / 'toolchain/msys64/ucrt64'
SOURCE = ROOT / 'native-port/modo_rdl_import.cpp'


def setting(lines, start, key):
    """A value from the block of build.ninja that begins at line start."""
    for line in lines[start + 1:start + 20]:
        if line.strip().startswith(key + ' = '):
            return line.split(' = ', 1)[1].strip()
    raise RuntimeError('The MoonRay build does not say its ' + key)


def main():
    lines = (BUILD / 'build.ninja').read_text(encoding='utf-8', errors='replace').splitlines()
    compiled = next(i for i, line in enumerate(lines) if line.startswith('build scene-rdl2/cmd/rdl2_cmd/rdl2_print/CMakeFiles/rdl2_print.dir/rdl2_print.cc.obj:'))
    linked = next(i for i, line in enumerate(lines) if line.startswith('build bin/rdl2_print.exe:'))
    target = BUILD / 'bin/modo_rdl_import.exe'
    command = ' '.join(['g++', setting(lines, compiled, 'DEFINES'), setting(lines, compiled, 'FLAGS'), '-w', setting(lines, compiled, 'INCLUDES'),
                        '-I"%s"' % (UCRT / 'include').as_posix(), '"%s"' % SOURCE.as_posix(), '-o', '"%s"' % target.as_posix(),
                        setting(lines, linked, 'LINK_LIBRARIES')])
    env = dict(os.environ, PATH=str(UCRT / 'bin') + os.pathsep + os.environ.get('PATH', ''))
    done = subprocess.run(command, cwd=str(BUILD), env=env, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if done.returncode:
        raise SystemExit(done.stdout.decode(errors='replace')[-4000:])
    print('Built', target)
    for folder in sys.argv[1:]:
        shutil.copy2(target, Path(folder) / target.name)
        print('Copied into', folder)


if __name__ == '__main__':
    main()
