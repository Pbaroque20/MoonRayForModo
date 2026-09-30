include(MoonrayDso)
moonray_ispc_dso(ModoTextureMap
    DEPENDENCIES Moonray::rendering_shading Moonray::shading_ispc
                 SceneRdl2::render_util SceneRdl2::scene_rdl2)
target_link_libraries(ModoTextureMap PRIVATE ispc_runtime)
target_link_libraries(ModoTextureMap_proxy PRIVATE ispc_runtime)
