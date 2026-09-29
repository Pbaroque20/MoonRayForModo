"""Resolve the ray-acceleration/camera cycle inside a single Windows DLL."""
from pathlib import Path
root = Path(__file__).resolve().parents[1]
rendering = root / 'upstream/openmoonray/moonray/moonray/lib/rendering'
path = rendering / 'rt/CMakeLists.txt'
text = path.read_text(encoding='utf-8')
if 'set(component rendering_rt_objects)' not in text:
    text = text.replace('set(component rendering_rt)', '''set(component rendering_rt)
set(rt_library_type SHARED)
if(MOONRAY_WINDOWS_DESKTOP)
    set(component rendering_rt_objects)
    set(rt_library_type OBJECT)
endif()''')
    text = text.replace('add_library(${component} SHARED "")', 'add_library(${component} ${rt_library_type} "")')
    text += '''
if(MOONRAY_WINDOWS_DESKTOP)
    add_library(rendering_rt INTERFACE)
    add_library(${PROJECT_NAME}::rendering_rt ALIAS rendering_rt)
    target_link_libraries(rendering_rt INTERFACE rendering_pbr)
    install(TARGETS rendering_rt EXPORT ${exportGroup})
endif()
'''
    path.write_text(text, encoding='utf-8')
path = rendering / 'pbr/CMakeLists.txt'
text = path.read_text(encoding='utf-8')
if 'rendering_rt_objects' not in text:
    text = text.replace('        ${PROJECT_NAME}::rendering_rt\n', '')
    text += '''
if(MOONRAY_WINDOWS_DESKTOP)
    target_link_libraries(rendering_pbr PRIVATE rendering_rt_objects)
else()
    target_link_libraries(rendering_pbr PUBLIC ${PROJECT_NAME}::rendering_rt)
endif()
'''
    path.write_text(text, encoding='utf-8')
