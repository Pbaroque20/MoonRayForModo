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

This runtime is not included in the plugin distribution. It includes multiple
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
They are local development dependencies and are not included in the kit ZIP.
The native source-port outputs are not a redistributable runtime bundle.
