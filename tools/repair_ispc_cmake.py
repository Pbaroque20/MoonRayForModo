"""Fix CMake's MSVC-only ISPC archive rule in the project-local toolchain."""
from pathlib import Path
root = Path(__file__).resolve().parents[1]
path = root / 'toolchain/msys64/ucrt64/share/cmake/Modules/Platform/Windows-Intel-ISPC.cmake'
text = path.read_text(encoding='utf-8')
marker = '# MoonRayForModo: native GNU archive tool with Windows ISPC.'
if marker not in text:
    text += '''
# MoonRayForModo: native GNU archive tool with Windows ISPC.
if(CMAKE_AR MATCHES "ar(\\\\.exe)?$")
  set(CMAKE_ISPC_CREATE_STATIC_LIBRARY "<CMAKE_AR> qc <TARGET> <OBJECTS>")
endif()
'''
    path.write_text(text, encoding='utf-8')
print('Project-local ISPC archive rule ready')
