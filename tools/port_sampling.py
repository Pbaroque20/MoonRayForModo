"""Create native COFF sampling tables and concatenate chunks without a shell."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
directory = root / 'upstream/openmoonray/moonray/moonray/lib/rendering/pbr'
path = directory / 'CMakeLists.txt'
text = path.read_text(encoding='utf-8')
text = text.replace('string(REGEX REPLACE "[\\/\\.\\-]" "_" base ${binFile})',
                    'string(REGEX REPLACE "[^a-zA-Z0-9_]" "_" base "${binFile}")')
old = '''COMMAND ${CMAKE_COMMAND}
            -DINPUT_FILES="${chunks}"
            -DOUTPUT_FILE="${temp_pmj02_best_candidate}"
            -P ${CMAKE_CURRENT_SOURCE_DIR}/cmake/ConcatenateBinaryFiles.cmake'''
new = '''COMMAND "${PYTHON_EXECUTABLE}"
            "${CMAKE_CURRENT_SOURCE_DIR}/cmake/ConcatenateBinaryFiles.py"
            "${temp_pmj02_best_candidate}" ${chunks}'''
text = text.replace(old, new)
text = text.replace('COMMENT "Concatenating PMJ02 sampling binary chunks"',
                    'COMMENT "Concatenating PMJ02 sampling binary chunks"\n        VERBATIM')
if 'set(sampling_object_format ' not in text:
    text = text.replace('# translate ".bin" source files to ".o" files', '''set(sampling_object_format elf64-x86-64)
if(WIN32)
    set(sampling_object_format pe-x86-64)
endif()
# translate ".bin" source files to ".o" files''')
    text = text.replace('--output-target=elf64-x86-64', '--output-target=${sampling_object_format}')
    text = text.replace('"${objFile}")', '"${objFile}"\n            VERBATIM)')
path.write_text(text, encoding='utf-8')
(directory / 'cmake/ConcatenateBinaryFiles.py').write_text('''# Copyright 2026 MoonRayForModo contributors
# SPDX-License-Identifier: Apache-2.0
"""Stream binary chunks, including files whose paths contain spaces."""
import shutil
import sys
from pathlib import Path

output = Path(sys.argv[1])
with output.open('wb') as destination:
    for name in sys.argv[2:]:
        with Path(name).open('rb') as source:
            shutil.copyfileobj(source, destination, 1024 * 1024)
''', encoding='utf-8')
