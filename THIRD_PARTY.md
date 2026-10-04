# Third-party components

The plugin's original project code is licensed under MIT (see `LICENSE`). It uses
Modo's installed `lx`, `lxifc`, `lxu`, `modo`, and PySide2 APIs. No Modo SDK or
Foundry binaries are included in the plugin ZIP.

MoonRay is a separate open-source project under Apache-2.0:
https://github.com/OpenMoonRay/openmoonray

For local testing, a community native Windows binary archive was downloaded from:
https://github.com/scrubjay/YUpBlender/releases/tag/v5.3-yup-alpha

Asset: `openmoonray_win64_runtime.zip`
Size: 456503125 bytes
Published SHA-256, verified against the downloaded file:
`863393434dee030218b7b9bd1ab5038b9af51309f33d00e90b67985da26302a2`

This historical community runtime is not included in the plugin distribution. It includes multiple
third-party dependencies and must retain their applicable license notices if
redistributed. No provenance or official support claim is made for the community
build. A checksum match verifies the downloaded release asset, not its correctness
or compatibility. It failed the real render test on this computer.

The source-port patches reference OpenMoonRay files bearing Apache-2.0 notices;
those notices are retained. Upstream source checkouts and downloads are excluded
from the plugin package.

The independent source build additionally uses official ISPC v1.31.0 runtime
sources, whose BSD license is retained in `upstream/ispc-runtime/LICENSE.txt`,
log4cplus REL_2_1_2 and Random123 v1.14.0 with their source license files intact.
Pinned origins and checksums are recorded in `patches/native-windows/sources.json`.
MSYS2/UCRT64 compiler and library packages remain in `toolchain/msys64`, together
with their installed license files under the relevant `share/licenses` directories.
The compiler toolchain is not included in the kit ZIP. Runtime dependency DLLs are supplied in the separate runtime ZIP.
The development release packages the separately built native source-port outputs with staged dependencies and their license notices.

XPU development uses official NVIDIA CUDA 12.8 components and OptiX 7.6 headers.
Pinned archive checksums and the OptiX Git commit are in
`patches/native-windows/xpu-sources.json`. NVIDIA licenses remain in their local
component directories and staged XPU runtime `licenses` folder. They are not
relicensed under MIT or Apache 2.0. No NVIDIA binaries are committed to this repo.

## Development release 0.3.40

The runtime release asset contains the staged `xpu-adaptive-buckets-0332` build,
not the historical community archive described above. Plugin source and the
geometry adapter are supplied separately in the kit asset. No Modo application,
SDK headers, CUDA toolkit, or NVIDIA driver is distributed.

The runtime ZIP retains CUDA/OptiX notices and includes collected upstream and
MSYS2 dependency license files under `runtime/licenses`. Dependency package
metadata and source locations are recorded under `runtime/provenance`; native
port source pins are also in `patches/native-windows/sources.json` in this repo.
Third-party components retain their own licenses; the plugin MIT license does
not relicense them. Bundled example assets retain their accompanying notices.

Release checksums identify the packaged files. They do not certify production
readiness or compatibility with a clean Windows installation.
