cmake_minimum_required(VERSION 3.23)
project(MoonLight LANGUAGES CXX)
if(NOT WIN32 OR NOT MINGW)
  message(FATAL_ERROR "MoonLight builds with the project's native Windows MinGW compiler")
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
set(MOONLIGHT_PTX "${CMAKE_BINARY_DIR}/shaders/MoonLightKernel.ptx")
file(GLOB deviceHeaders CONFIGURE_DEPENDS src/device/*.h)
add_custom_command(OUTPUT "${MOONLIGHT_PTX}"
  COMMAND "${PYTHON_EXECUTABLE}" "${ROOT}/tools/compile_moonlight_ptx.py"
    "${CMAKE_CURRENT_SOURCE_DIR}/src/device/kernel.cu" "${MOONLIGHT_PTX}"
  DEPENDS src/device/kernel.cu ${deviceHeaders} "${ROOT}/tools/compile_moonlight_ptx.py"
  VERBATIM)
add_custom_target(moonlight_ptx DEPENDS "${MOONLIGHT_PTX}")

add_library(moonlight STATIC src/renderer.cpp)
target_include_directories(moonlight PUBLIC include PRIVATE src)
target_link_libraries(moonlight PRIVATE CUDA::cudart OptiX::OptiX)
add_dependencies(moonlight moonlight_ptx)

add_executable(moonlight_probe probe/moonlight_probe.cpp)
target_link_libraries(moonlight_probe PRIVATE moonlight)
target_link_options(moonlight_probe PRIVATE -static-libgcc -static-libstdc++)

# Publishes frames through the same shared-memory mailbox as the MoonRay session.
add_executable(moonlight_session session/moonlight_session.cpp session/scene_loader.cpp)
target_include_directories(moonlight_session PRIVATE "${ROOT}/native-port")
target_link_libraries(moonlight_session PRIVATE moonlight)
target_link_options(moonlight_session PRIVATE -static -static-libgcc -static-libstdc++)
