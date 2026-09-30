include(MoonrayDso)
moonray_ispc_dso(ModoNormalMap DEPENDENCIES Moonray::rendering_shading Moonray::shading_ispc SceneRdl2::scene_rdl2)
target_link_libraries(ModoNormalMap PRIVATE ispc_runtime)
target_link_libraries(ModoNormalMap_proxy PRIVATE ispc_runtime)
