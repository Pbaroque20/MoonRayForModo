"""Prepare include junctions and narrowly scoped renderer build portability changes."""
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
source = root / 'upstream/openmoonray/moonray'

def junction(link, target):
    target.mkdir(parents=True, exist_ok=True)
    link.parent.mkdir(parents=True, exist_ok=True)
    if not link.exists():
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], check=True)

for name, buildname in [('scene_rdl2', 'scene-rdl2'), ('mcrt_denoise', 'mcrt-denoise'), ('moonray', 'moonray')]:
    junction(root / 'native-port/include' / name, source / name / 'lib')
    for build in ('native-avx', 'native-renderer-avx'):
        base = root / 'build' / build / buildname
        junction(base / 'include' / name, base / 'lib')
    if name == 'scene_rdl2':
        continue
    path = source / name / 'CMakeLists.txt'
    text = path.read_text(encoding='utf-8')
    old = 'file(CREATE_LINK ../lib ${PROJECT_BINARY_DIR}/include/${PACKAGE_NAME} SYMBOLIC)'
    if 'if(NOT IS_DIRECTORY ${PROJECT_BINARY_DIR}/include/${PACKAGE_NAME})' not in text:
        text = text.replace(old, 'if(NOT IS_DIRECTORY ${PROJECT_BINARY_DIR}/include/${PACKAGE_NAME})\n    ' + old + '\nendif()')
    path.write_text(text, encoding='utf-8')
    for path in (source / name).rglob('*.cmake'):
        text = path.read_text(encoding='utf-8')
        after = text.replace('-march=core-avx2', '-march=${OMR_X86_ARCH}')
        if text != after:
            path.write_text(after, encoding='utf-8')
    for path in (source / name).rglob('CMakeLists.txt'):
        text = path.read_text(encoding='utf-8')
        after = text.replace('ISPC_HEADER_DIRECTORY /${relBinDir}', 'ISPC_HEADER_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}')
        if text != after:
            path.write_text(after, encoding='utf-8')
