"""Unify ray tracing, integrator and render driver callbacks in one Windows DLL."""
from pathlib import Path
root = Path(__file__).resolve().parents[1]
rendering = root / 'upstream/openmoonray/moonray/moonray/lib/rendering'
path = rendering / 'pbr/CMakeLists.txt'
text = path.read_text(encoding='utf-8')
if 'set(component rendering_pbr_objects)' not in text:
    text = text.replace('set(component rendering_pbr)', '''set(component rendering_pbr)
set(pbr_library_type SHARED)
if(MOONRAY_WINDOWS_DESKTOP)
    set(component rendering_pbr_objects)
    set(pbr_library_type OBJECT)
endif()''')
    text = text.replace('add_library(${component} SHARED "")', 'add_library(${component} ${pbr_library_type} "")')
    text = text.replace('target_link_libraries(rendering_pbr ', 'target_link_libraries(${component} ')
    text += '''
if(MOONRAY_WINDOWS_DESKTOP)
    set_property(TARGET ${component} PROPERTY DESKTOP_SAMPLING_OBJECTS "${samplerObjs}")
    add_library(rendering_pbr INTERFACE)
    add_library(${PROJECT_NAME}::rendering_pbr ALIAS rendering_pbr)
    target_link_libraries(rendering_pbr INTERFACE rendering_rndr)
    install(TARGETS rendering_pbr EXPORT ${exportGroup})
endif()
'''
    path.write_text(text, encoding='utf-8')
path = rendering / 'rndr/CMakeLists.txt'
text = path.read_text(encoding='utf-8')
if 'rendering_pbr_objects' not in text:
    text = text.replace('        ${PROJECT_NAME}::rendering_pbr\n', '').replace('        ${PROJECT_NAME}::rendering_rt\n', '')
    text += '''
if(MOONRAY_WINDOWS_DESKTOP)
    target_link_libraries(rendering_rndr PUBLIC rendering_pbr_objects rendering_rt_objects)
    foreach(part 00 01 02 03 04 05)
        target_sources(rendering_rndr PRIVATE $<TARGET_OBJECTS:rendering_pbr_ispc_${part}>)
    endforeach()
    get_target_property(sampling rendering_pbr_objects DESKTOP_SAMPLING_OBJECTS)
    get_target_property(pbr_binary rendering_pbr_objects BINARY_DIR)
    foreach(object IN LISTS sampling)
        set_source_files_properties("${pbr_binary}/${object}" PROPERTIES GENERATED TRUE EXTERNAL_OBJECT TRUE)
        target_sources(rendering_rndr PRIVATE "${pbr_binary}/${object}")
    endforeach()
else()
    target_link_libraries(rendering_rndr PUBLIC ${PROJECT_NAME}::rendering_pbr ${PROJECT_NAME}::rendering_rt)
endif()
'''
    path.write_text(text, encoding='utf-8')
