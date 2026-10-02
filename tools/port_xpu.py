"""Apply Windows XPU adaptations to the pinned upstream checkout."""
from pathlib import Path
root=Path(__file__).resolve().parents[1]
base=root/'upstream/openmoonray/moonray'
for component in ('moonray','mcrt_denoise'):
    p=base/component/'CMakeLists.txt';s=p.read_text()
    if 'if(NOT TARGET CUDA::cudart)' not in s:
        s=s.replace('    find_package(CUDAToolkit REQUIRED) # built-in','    if(NOT TARGET CUDA::cudart)\n        find_package(CUDAToolkit REQUIRED)\n    endif()')
    if component=='moonray' and 'if(NOT MOONRAY_WINDOWS_XPU)' not in s:
        start=s.index('    include(CheckLanguage)');end=s.index('    if(NOT TARGET CUDA::cudart)',start)
        s=s[:start]+'    if(NOT MOONRAY_WINDOWS_XPU)\n'+s[start:end]+'    endif()\n'+s[end:]
    p.write_text(s)
p=base/'moonray/lib/rendering/rt/CMakeLists.txt';s=p.read_text()
if 'compile_xpu_ptx.py' not in s:
    start=s.index('    add_library(${optixLib} OBJECT)');end=s.index('\nendif()',start)
    original=s[start:end]
    custom="""    if(MOONRAY_WINDOWS_XPU)
        file(GLOB xpuHeaders CONFIGURE_DEPENDS gpu/optix/*.h gpu/*.h)
        set(XPU_PTX "${CMAKE_BINARY_DIR}/shaders/OptixGPUPrograms.ptx")
        add_custom_command(OUTPUT "${XPU_PTX}"
            COMMAND "${PYTHON_EXECUTABLE}" "${ROOT}/tools/compile_xpu_ptx.py" "${XPU_PTX}"
            DEPENDS gpu/optix/OptixGPUPrograms.cu ${xpuHeaders} "${ROOT}/tools/compile_xpu_ptx.py"
            VERBATIM)
        add_custom_target(${optixLib} DEPENDS "${XPU_PTX}")
        add_dependencies(${component} ${optixLib})
    else()
"""
    s=s[:start]+custom+original+'\n    endif()'+s[end:]
    s=s.replace('    # install optix ptx files\n    install(', '    # install optix ptx files\n    if(MOONRAY_WINDOWS_XPU)\n        install(FILES "${XPU_PTX}" DESTINATION shaders)\n    else()\n    install(')
    s=s.replace('        FILES $<TARGET_OBJECTS:${optixLib}>\n        DESTINATION shaders\n    )','        FILES $<TARGET_OBJECTS:${optixLib}>\n        DESTINATION shaders\n    )\n    endif()')
    p.write_text(s)
for relative in ('moonray/lib/rendering/rt/gpu/optix/OptixGPUUtils.cc','mcrt_denoise/lib/denoiser/OptixDenoiserImpl.cc'):
    p=base/relative;s=p.read_text()
    if '// Windows CUDA driver capability check' not in s:
        start=s.index('    int major, minor;');end=s.index('    cudaFree(0);',start)
        old=s[start:end]
        s=s[:start]+"""#if defined(_WIN32)
    // Windows CUDA driver capability check; optixInit verifies OptiX ABI support.
    int cudaVersion = 0;
    if (cudaDriverGetVersion(&cudaVersion) != cudaSuccess || cudaVersion < 12000) {
        *errorMsg = "CUDA driver unavailable or too old (CUDA 12 required)";
        return false;
    }
#else
"""+old+'#endif\n\n'+s[end:]
        p.write_text(s)
print('Applied Windows XPU build and driver discovery adaptations')

p=base/'moonray/lib/rendering/rt/gpu/optix/EmbreeSupport.h';s=p.read_text()
old='constexpr __device__ float pos_inf = std::numeric_limits<float>::infinity();\nconstexpr __device__ float inf = pos_inf;\nconstexpr __device__ float neg_inf = -pos_inf;'
if '#if defined(__CUDACC_RTC__)' not in s:
    s=s.replace(old,'#if defined(__CUDACC_RTC__)\n#define pos_inf (__int_as_float(0x7f800000))\n#define inf pos_inf\n#define neg_inf (-pos_inf)\n#else\n'+old+'\n#endif')
    p.write_text(s)

p=base/'moonray/lib/statistics/Formatters.h';s=p.read_text()
s=s.replace('return std::locale("");','return std::locale::classic(); // deterministic fallback without an installed OS locale')
p.write_text(s)
