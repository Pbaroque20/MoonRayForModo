# Native Windows XPU (0.2.1 development)

MoonRay XPU runs ray intersections on an NVIDIA CUDA/OptiX GPU and shading on the
CPU. It is a hybrid mode; CPU AVX compatibility remains relevant. This integration
uses the existing material, geometry, texture, AOV and preview pipeline.

In MoonRay Render Setup, open **Runtime and CPU** and choose **Rendering mode >
XPU (NVIDIA GPU + CPU)**. CPU AVX and CPU scalar remain selectable. New scenes
default to XPU when the installed runtime contains its GPU program and CUDA DLL.
Store render settings in scene to preserve the selection. Preview and animation
use the same choice. Completion reports XPU active or a CPU fallback; Render Log
contains device identification, memory use and GPU ray utilization.

The GPU needs enough VRAM for acceleration structures and ray buffers. MoonRay
may fall back to CPU if GPU setup fails or runs out of memory. XPU inherits vector
mode limitations; upstream also documents limits on round Bezier curves and more
than two motion samples. Performance depends on scene size and workload. A small
preview can be slower because GPU setup has a fixed cost. No speedup is promised.

## Building locally

1. Run `python tools/setup_xpu.py` to fetch pinned official NVIDIA components into
   the project. Archive SHA-256 checksums and the OptiX revision are recorded in
   `patches/native-windows/xpu-sources.json`. No system driver is installed.
2. Run `python tools/port_xpu.py` and `python tools/port_denoise.py`, then `python tools/port_execution_mode.py`, after the existing Windows source-port steps. The latter validates denoiser input and applies the MinGW OptiX header correction.
3. Run `python tools/build_native.py --renderer --dsos --xpu --skip-tests`.
4. Run `python tools/stage_runtime.py --xpu --destination runtime/xpu-avx-20261001`.
5. Run `python tools/check_xpu_render.py runtime/xpu-avx-20261001` for the small
   standalone check, only when render testing is desired.

The incremental build directory is shared with the CPU build. The installed CPU
runtime is preserved separately. Omitting --xpu reconfigures the build for CPU;
staging refuses a mode mismatch and refuses the legacy CPU destination for XPU.

CUDA 12.8 NVRTC compiles the OptiX PTX program without requiring MSVC/nvcc as the
host compiler. Host C++ remains MinGW, using the CUDA runtime C ABI and the Windows
OptiX loader. Device-only standard-header shims cover the small set needed by the
upstream curve intersectors. IEEE infinity constants preserve their bit patterns.
OptiX 7.6 matches this pinned MoonRay source's API. The PTX target is compute 7.5;
the NVIDIA driver compiles it for the installed GPU. Windows driver capability
checks replace Linux /sys lookups. Statistics use a deterministic locale fallback.

Runtime staging includes cudart, the PTX program and applicable NVIDIA notices.
The NVIDIA components retain their own licenses; the plugin's MIT license does
not relicense them. The upstream renderer remains Apache 2.0. This is a local
development runtime, not a completed redistributable installer.

Reference: https://docs.openmoonray.org/user-reference/execution-modes/

## Local check, October 1, 2026

The 128 x 128 standalone fixture completed on the RTX 3090 (driver 580.97),
with no CPU fallback. GPU bundled intersection utilization was 99.90%; GPU
occlusion utilization was 100.00%. The float EXR had finite, nonblack RGB pixels,
with no NaN or infinity values. The first attempt exposed a statistics-locale
crash after rendering; the rebuilt runtime passed after fixing that fallback.
This checks basic XPU execution, not full-scene parity or a performance benchmark.
Modo scene/UI interaction and broader scene coverage remain untested.
