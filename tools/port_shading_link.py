"""Keep C++ shading and its ISPC callbacks in one DLL on Windows."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
lib = root / 'upstream/openmoonray/moonray/moonray/lib'
for path in (lib / 'rendering/geom').rglob('*'):
    if path.suffix in ('.h', '.cc'):
        original = path.read_text(encoding='utf-8')
        text = re.sub(r'\buint\b', 'unsigned int', original)
        if text != original:
            path.write_text(text, encoding='utf-8')
path = lib / 'rendering/rt/GeometryManager.cc'
text = path.read_text(encoding='utf-8').replace('#ifndef __APPLE__', '#if !defined(__APPLE__) && !defined(_WIN32)')
path.write_text(text, encoding='utf-8')

path = lib / 'rendering/shading/ispc/CMakeLists.txt'
text = path.read_text(encoding='utf-8')
if 'set(eval_component ' not in text:
    text = re.sub(r'\bshading_eval_ispc\b', '${eval_component}', text)
    text = re.sub(r'\bshading_ispc\b', '${bsdf_component}', text)
    text = text.replace('SHARED ""', '${shading_library_type} ""')
    text = text.replace('add_library(${PROJECT_NAME}::${eval_component} ALIAS ${eval_component})',
                        'if(NOT MOONRAY_WINDOWS_DESKTOP)\nadd_library(${PROJECT_NAME}::shading_eval_ispc ALIAS ${eval_component})\nendif()')
    text = text.replace('add_library(${PROJECT_NAME}::${bsdf_component} ALIAS ${bsdf_component})',
                        'if(NOT MOONRAY_WINDOWS_DESKTOP)\nadd_library(${PROJECT_NAME}::shading_ispc ALIAS ${bsdf_component})\nendif()')
    text = '''# Windows DLLs must resolve the mutual C++/ISPC callbacks at link time.
set(eval_component shading_eval_ispc)
set(bsdf_component shading_ispc)
set(shading_library_type SHARED)
if(MOONRAY_WINDOWS_DESKTOP)
    set(eval_component shading_eval_objects)
    set(bsdf_component shading_bsdf_objects)
    set(shading_library_type OBJECT)
endif()
''' + text
    text += '''
if(MOONRAY_WINDOWS_DESKTOP)
    # Existing public dependency names all refer to the single owning DLL.
    add_library(shading_eval_ispc INTERFACE)
    add_library(${PROJECT_NAME}::shading_eval_ispc ALIAS shading_eval_ispc)
    target_link_libraries(shading_eval_ispc INTERFACE rendering_shading)
    add_library(shading_ispc INTERFACE)
    add_library(${PROJECT_NAME}::shading_ispc ALIAS shading_ispc)
    target_link_libraries(shading_ispc INTERFACE rendering_shading)
    install(TARGETS shading_eval_ispc shading_ispc EXPORT ${exportGroup})
endif()
'''
    path.write_text(text, encoding='utf-8')

path = lib / 'rendering/shading/CMakeLists.txt'
text = path.read_text(encoding='utf-8')
if 'shading_eval_objects' not in text:
    text = text.replace('        ${PROJECT_NAME}::shading_eval_ispc\n        ${PROJECT_NAME}::shading_ispc\n', '')
    text += '''
if(MOONRAY_WINDOWS_DESKTOP)
    target_link_libraries(rendering_shading PRIVATE shading_eval_objects shading_bsdf_objects)
else()
    target_link_libraries(rendering_shading PUBLIC ${PROJECT_NAME}::shading_eval_ispc ${PROJECT_NAME}::shading_ispc)
endif()
'''
    path.write_text(text, encoding='utf-8')
