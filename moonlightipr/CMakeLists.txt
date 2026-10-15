cmake_minimum_required(VERSION 3.23)
project(MoonLightIPR LANGUAGES CXX)
if(NOT WIN32 OR NOT MINGW)
  message(FATAL_ERROR "MoonLightIPR builds with the project's native Windows MinGW compiler")
endif()
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
get_filename_component(ROOT "${CMAKE_CURRENT_SOURCE_DIR}/.." ABSOLUTE)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
add_compile_definitions(NOMINMAX WIN32_LEAN_AND_MEAN)

# Same pinned CUDA runtime and OptiX headers as the XPU renderer build.
include("${ROOT}/native-port/cmake/WindowsXpu.cmake")
set(PYTHON_EXECUTABLE "${ROOT}/toolchain/msys64/ucrt64/bin/python.exe")

# Device code is compiled by NVRTC, so no host CUDA compiler is needed.
set(MOONLIGHTIPR_PTX "${CMAKE_BINARY_DIR}/shaders/MoonLightIPRKernel.ptx")
file(GLOB deviceHeaders CONFIGURE_DEPENDS src/device/*.h)
add_custom_command(OUTPUT "${MOONLIGHTIPR_PTX}"
  COMMAND "${PYTHON_EXECUTABLE}" "${ROOT}/tools/compile_moonlightipr_ptx.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/device/kernel.cu" "${MOONLIGHTIPR_PTX}"
  DEPENDS src/device/kernel.cu ${deviceHeaders} "${ROOT}/tools/compile_moonlightipr_ptx.py"
  VERBATIM)
add_custom_target(moonlightipr_ptx DEPENDS "${MOONLIGHTIPR_PTX}")

# The compositor's device program: precise arithmetic, so that it matches the processor (composite/ops.h).
set(COMPOSITE_PTX "${CMAKE_BINARY_DIR}/shaders/MoonLightIPRComposite.ptx")
add_custom_command(OUTPUT "${COMPOSITE_PTX}"
  COMMAND "${PYTHON_EXECUTABLE}" "${ROOT}/tools/compile_moonlightipr_ptx.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/composite/kernel.cu" "${COMPOSITE_PTX}" --precise
  DEPENDS composite/kernel.cu composite/ops.h "${ROOT}/tools/compile_moonlightipr_ptx.py"
  VERBATIM)
add_custom_target(composite_ptx DEPENDS "${COMPOSITE_PTX}")

add_library(moonlightipr STATIC src/renderer.cpp)
target_include_directories(moonlightipr PUBLIC include PRIVATE src)
target_link_libraries(moonlightipr PRIVATE CUDA::cudart OptiX::OptiX)
add_dependencies(moonlightipr moonlightipr_ptx)

add_executable(moonlightipr_probe probe/moonlightipr_probe.cpp)
target_link_libraries(moonlightipr_probe PRIVATE moonlightipr)
target_link_options(moonlightipr_probe PRIVATE -static-libgcc -static-libstdc++)

# Publishes frames through the same shared-memory mailbox as the MoonRay session.
add_executable(moonlightipr_session session/moonlightipr_session.cpp session/scene_loader.cpp session/subdivide.cpp)
target_include_directories(moonlightipr_session PRIVATE "${ROOT}/native-port")
target_link_libraries(moonlightipr_session PRIVATE moonlightipr)
target_link_options(moonlightipr_session PRIVATE -static -static-libgcc -static-libstdc++)

# The scene compositor: the same steps on the graphics card or the processor.
add_executable(modo_composite composite/composite.cpp)
target_link_libraries(modo_composite PRIVATE CUDA::cudart)
target_link_options(modo_composite PRIVATE -static -static-libgcc -static-libstdc++)
add_dependencies(modo_composite composite_ptx)
