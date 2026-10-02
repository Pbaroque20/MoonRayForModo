# Optional CUDA C ABI and OptiX headers for the MinGW renderer; PTX uses NVRTC.
set(XPU_ROOT "${ROOT}/toolchain/xpu")
set(XPU_CUDART "${XPU_ROOT}/cuda_cudart-windows-x86_64-12.8.90-archive")
set(XPU_NVCC "${XPU_ROOT}/cuda_nvcc-windows-x86_64-12.8.93-archive")
set(OptiX_INCLUDE_DIRS "${XPU_ROOT}/optix-dev/include" CACHE PATH "" FORCE)
foreach(required "${XPU_CUDART}/lib/x64/cudart.lib" "${OptiX_INCLUDE_DIRS}/optix.h")
  if(NOT EXISTS "${required}")
    message(FATAL_ERROR "XPU dependency missing: ${required}")
  endif()
endforeach()
add_library(CUDA::cudart INTERFACE IMPORTED GLOBAL)
set_target_properties(CUDA::cudart PROPERTIES
  INTERFACE_INCLUDE_DIRECTORIES "${XPU_CUDART}/include;${XPU_NVCC}/include"
  INTERFACE_LINK_LIBRARIES "${XPU_CUDART}/lib/x64/cudart.lib")

add_library(OptiX::OptiX INTERFACE IMPORTED GLOBAL)
set_target_properties(OptiX::OptiX PROPERTIES
  INTERFACE_INCLUDE_DIRECTORIES "${OptiX_INCLUDE_DIRS}"
  INTERFACE_LINK_LIBRARIES cfgmgr32)
