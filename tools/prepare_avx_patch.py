"""Generate (do not apply) an ISA configuration patch for pinned upstream sources.

This is build preparation, NOT a Windows port and NOT a tested renderer rebuild.
It preserves the existing eight-wide ISPC ABI while permitting AVX1 code generation.
"""
import difflib
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
source = ROOT / 'upstream/openmoonray'
paths = [
    'cmake_modules/cmake/OMR_Platform.cmake',
    'cmake_modules/cmake/MoonrayDso.cmake',
    'moonray/moonray/cmake/MoonrayCompileOptions.cmake',
    'moonray/scene_rdl2/cmake/SceneRdl2CompileOptions.cmake',
]
patch = []
for relative in paths:
    parts = relative.split('/')
    depth = 1 if parts[0] == 'cmake_modules' else 2
    repo = source.joinpath(*parts[:depth])
    git_path = '/'.join(parts[depth:])
    before = subprocess.check_output(['git', '-C', str(repo), 'show', 'HEAD:' + git_path]).decode('utf-8')
    if relative.endswith('OMR_Platform.cmake'):
        needle = '    set(GLOBAL_ISPC_INSTRUCTION_SETS avx2-i32x8)'
        assert before.count(needle) == 1, 'Unexpected upstream version'
        after = before.replace(needle,
            '    set(OMR_X86_ARCH "core-avx2" CACHE STRING "C/C++ x86 target architecture")\n'
            '    set(OMR_ISPC_TARGET "avx2-i32x8" CACHE STRING "ISPC target; retain eight-wide lanes")\n'
            '    set(GLOBAL_ISPC_INSTRUCTION_SETS ${OMR_ISPC_TARGET})')
    else:
        needle = '-march=core-avx2'
        assert needle in before, 'Unexpected upstream version'
        after = before.replace(needle, '-march=${OMR_X86_ARCH}')
        # The architecture setting must also control FMA. Ivy Bridge has no FMA.
        # -march=core-avx2 already enables FMA for the unchanged upstream default.
        after = after.replace('                -mfma                           # x86 options\n', '')
    patch.extend(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                    fromfile='a/' + relative, tofile='b/' + relative))
destination = ROOT / 'patches/configurable-x86-isa.patch'
destination.parent.mkdir(exist_ok=True)
destination.write_text(''.join(patch), encoding='utf-8')
print(destination)
