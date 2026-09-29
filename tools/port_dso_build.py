"""Make scene-plugin generation and staging work in a native Windows build."""
from pathlib import Path
root = Path(__file__).resolve().parents[1]
path = root / 'upstream/openmoonray/cmake_modules/cmake/MoonrayDso.cmake'
text = path.read_text(encoding='utf-8')
if 'set(MOONRAY_DSO_STAGE_COMMAND' not in text:
    text = '''set(MOONRAY_DSO_STAGE_COMMAND create_symlink)
if(WIN32)
    set(MOONRAY_DSO_STAGE_COMMAND copy_if_different)
endif()
''' + text
    text = text.replace('-E create_symlink', '-E ${MOONRAY_DSO_STAGE_COMMAND}')
    text = text.replace('${ISPC_DSO_GEN_SCRIPT} ${jsonSrc}', '"${PYTHON_EXECUTABLE}" "${ISPC_DSO_GEN_SCRIPT}" "${jsonSrc}"')
    text = text.replace('"Generating DSO files from ${jsonSrc}"', '"Generating DSO files from ${jsonSrc}"\n        VERBATIM')
    text = text.replace('set(proxyDsoPath "${CMAKE_CURRENT_BINARY_DIR}/${configDir}/${name}.so.proxy")',
                        'set(proxyDsoPath "$<TARGET_FILE:${name}_proxy>")')
    path.write_text(text, encoding='utf-8')
