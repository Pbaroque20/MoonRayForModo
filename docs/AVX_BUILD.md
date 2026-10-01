# Native Windows / AVX1 source port

This independent experimental desktop port targets Modo 16.1v9 on Windows and
the local Intel Core i7-4930K. It uses public OpenMoonRay source, without the
unavailable source or build configuration of the community Windows binary.

## Verified results

The complete CPU renderer executable and its upstream shader DSOs compile and
link. Real scalar and vectorized renders pass on this AVX1-only CPU, with varied
image pixels and successful process exits. An invalid output path fails promptly.
Seven native component tests pass. Real Qt process cancellation, replacement
rendering, image delivery and temporary-file cleanup pass.

`native-port/moonshine/CMakeLists.txt` builds the real Moonshine DwaBaseMaterial
and its interpolation, projection, glitter and material libraries with the same
AVX1 flags. Generated ISPC headers are staged explicitly for Windows. The small
`patches/native-windows/moonshine.patch` fixes independent refraction roughness
being ignored by the mirror branch when reflection roughness is zero.

Original adapter DSOs add ordered texture blending, tangent normal/bump evaluation
and the NormalMap interface needed by Moonshine. Before installing a new build,
run `validate_surface_updates.py` and `validate_glass.py --moonshine` in addition
to the existing renderer/glass checks. The installer checks these shader hashes.

The kit is installed under `%APPDATA%/Luxology/Kits/MoonRayForModo`.
The exact `C:/Program Files/Modo16.1v9/modo/modo.exe` opened its visible preview.
A real mesh move automatically produced a different rendered image. The test
uses a native Modo transform command because direct channel writes from a timer
are outside Modo's required edit context.

Evidence:
- `build/native-renderer-avx/{configure,compile,test}.log`
- `runtime/native-avx/validated-render.json`
- `test-results/live-process/report.json`
- `test-results/live-preview/report.json`

These are focused smoke and component tests, not the full upstream regression
suite or production scene-parity validation. The Modo scene translator remains
limited; see README. This is a Custom View integration, not an F9 renderer.

## Build and install

Run from this project with a Python 3.9+ interpreter. The installed Modo launcher
is `C:/Program Files/Modo16.1v9/modo/resrc/python3kit/extra64/modopython.bat`.

1. `tools/prepare_renderer.py` prepares project-local source dependencies.
2. `tools/build_native.py --renderer --dsos` configures, builds and tests.
   Use `--build-only` for incremental builds; Ninja regenerates when needed.
   `MOONRAY_BUILD_JOBS` overrides the default eight jobs.
   `--skip-tests` explicitly builds without running tests; this does not validate
   a release. See `CPU_FEATURE_CANDIDATE.md` for the separate development-install
   route used when the user requests installation while keeping tests deferred.
3. `tools/stage_runtime.py` stages native binaries and recursively resolved DLL
   imports under `runtime/native-avx`, with source paths and SHA-256 checksums.
4. `tools/validate_renderer.py` checks scalar and vectorized images and failure
   cleanup. It creates the validation marker only on full success.
5. `tools/validate_live_process.py` runs the real Qt process lifecycle check.
6. With Modo closed, `tools/install_kit.py` installs this kit, backs up any prior
   copy of this kit, and checks the validated executable checksum.
7. `tools/launch_installed_probe.py` opens the exact Modo 16.1v9 executable and
   creates a separate test scene for the live-edit check.

`tools/test_native.py` reruns built native component tests without rebuilding.
The build driver changes PATH only for child processes and records build logs.
The scene-only build uses `--scene` and a separate build directory.

## AVX and Windows implementation

Compiler settings are GCC `-march=ivybridge -mno-avx2 -mno-fma -ffp-contract=off`
and ISPC `avx1-i32x8`. No WSL, AVX2 emulation, Linux renderer or remote service is
used. The runtime contains native Windows binaries. The project-local UCRT64
toolchain is under `toolchain/msys64`; MSYS2 supplies build tools only.

Port changes cover aligned allocation/free, Windows paths and loader handling,
endian conversion, fixed-width 64-bit scene serialization, Lua binary bytecode,
thread affinity, native NUMA allocation, address-based wait/notify, monotonic
time, process statistics, file-change polling and checkpoint file operations.

C++/ISPC shading objects share a Windows DLL; ray tracing, PBR and render-control
objects share another to resolve dependencies without Unix dynamic lookup.
Native sampling tables use COFF objects. Generated shader headers and proxy
import libraries have explicit build paths.

The Win64 ISPC mask ABI passes an explicitly 32-byte-aligned mask pointer.
GCC's implicit by-reference vector argument otherwise used a 16-byte-aligned
temporary, which faulted on an ISPC aligned AVX load. The native mask probe and
real vectorized render verify this fix.

Framebuffer ownership retains the aligned deleter when constructing shared
storage. Render shutdown releases and joins worker services before Windows DLL
detach, including failure paths. These fixes are covered by allocation and real
render/failed-output checks.

The official ISPC print runtime is compiled with Clang. The stack-probe adapter
delegates to the real GNU Windows guard-page probe; a component test checks
register and stack preservation. `tools/repair_ispc_cmake.py` fixes the local
CMake GNU archive rule; `tools/ispc_launcher.py` repairs dependency-path escaping
for directories containing spaces.

The Windows affinity implementation supports one processor group (up to 64
logical processors). Unicode path parity and checkpoint/interruption end-to-end
behavior are not fully validated. Optional Unix farm allocation, shared-memory
farm transport, telnet debugging and Athena telemetry are excluded. Local
rendering statistics remain enabled.

## Source preservation and distribution

`patches/native-windows/sources.json` records source URLs, pinned commits and
patch checksums. `installed-packages.txt` records dependency versions.
`tools/export_native_patches.py` exports the current changes and verifies them
against the source checkouts. Apply each repository patch to its pinned clean
revision. Do not also apply `configurable-x86-isa.patch`, which overlaps them.

The local package cache retains dependency downloads. Rolling package repositories
may not supply identical versions later. A fresh-machine bootstrap and
cross-machine deployment remain unverified. Local staging records 315 native
binaries; its manifest is in `runtime/native-avx/build-manifest.json`.

The glass adapter is maintained in `native-port/materials/ModoGlass`, with C++
and AVX ISPC implementations using MoonRay's coupled dielectric BSDFs. The
`moonray_desktop_renderer` target builds it and its proxy; `stage_runtime.py`
includes both. Run `validate_glass.py` after staging and before installing the
kit. Installation checks the validated glass module hashes as well as the renderer.

## Earlier community runtime

The downloaded community Windows runtime crashed at an AVX2 integer instruction
inside `rendering_pbr.dll`, including in scalar mode. It is not used by the new
installed kit. Earlier failure reports are retained separately from the
successful source-build reports.

Sources: [MoonRay](https://github.com/OpenMoonRay/openmoonray),
[ISPC v1.31.0](https://github.com/ispc/ispc/tree/v1.31.0),
[MSYS2](https://www.msys2.org/).
