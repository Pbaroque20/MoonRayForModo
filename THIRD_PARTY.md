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

Thanks to scrubjay for publishing that community Windows build of MoonRay with YUpBlender; it helped the early
testing of this plugin. None of its code or files are part of the plugin or of its runtime, which is built from
the OpenMoonRay sources listed below.

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

## MoonLightIPR

MoonLightIPR, the GPU preview engine, is not third-party software: it was created by Raphael Tobar and is
released under this project's MIT License. It is not a DreamWorks Animation product and is not affiliated
with or endorsed by DreamWorks Animation. It runs on NVIDIA OptiX and CUDA, whose notices are above.

MoonLightIPR's velvet lobe reads two tables taken unchanged from OpenMoonRay (`moonlightipr/src/device/velvet_tables.h`),
Copyright 2023-2024 DreamWorks Animation LLC, under the Apache License 2.0; they keep that notice and are not
relicensed under MIT. See `moonlightipr/NOTICE.md`.

## ISPC Texture Compressor

XPU2's texture overflow mode compresses textures with Intel's ISPC Texture Compressor (https://github.com/GameTechDev/ISPCTextureCompressor,
commit 79ddbc9; `upstream/ISPCTextureCompressor`, which Git ignores). `ispc_texcomp.cpp` and `kernel.ispc` are compiled unchanged into
`moonray_xpu2.exe`, and `xpu2/interactive/bc6h_core.h` is generated from the format's layouts in `kernel.ispc`.

Copyright 2017 Intel Corporation. MIT License: permission is hereby granted, free of charge, to any person obtaining a copy of this
software and associated documentation files, to deal in the Software without restriction, including without limitation the rights to use,
copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, subject to the copyright notice and this
permission notice being included in all copies or substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY
OF ANY KIND. See `license.txt` beside its source for the whole text.

## meshoptimizer

The realtime previews' mesh simplification uses meshoptimizer by Arseny Kapoulkine (zeux), version 0.22, under the MIT
License: https://github.com/zeux/meshoptimizer. Its simplifier, index generator and allocator (`allocator.cpp`,
`indexgenerator.cpp`, `simplifier.cpp`, with `meshoptimizer.h`) are compiled unchanged into the geometry adapter,
`bin/MoonRayGeometry.lx`, which `native-modo/simplify.cpp` (`MR_simplify`) calls, and into XPU2's preview session for its coarse first pass
(`xpu2/interactive/xpu2_meshopt.cc`, called by `coarse_geometry.h`). Its sources are not committed here
(`upstream/meshoptimizer`, from the v0.22 release, is ignored by Git). Its copyright and license notice ship with the kit
in `licenses/meshoptimizer-LICENSE.md`: Copyright (c) 2016-2024 Arseny Kapoulkine. Thanks to zeux for it.

## ISPC Texture Compressor

Block compression of XPU2's textures is to use Intel's ISPC Texture Compressor (GameTechDev), under the MIT License:
https://github.com/GameTechDev/ISPCTextureCompressor. The project is archived by Intel. It is not yet compiled into any
program here. Its sources are not committed (`upstream/ISPCTextureCompressor`, at 79ddbc9, is ignored by Git). Its copyright
and license notice ship with the kit in `licenses/ISPCTextureCompressor-LICENSE.txt`: Copyright 2017 Intel Corporation.
Thanks to Intel for it.
