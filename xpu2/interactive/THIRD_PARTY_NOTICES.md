# Licensing and third-party notices

Original XPU2 prototype code and documentation: copyright (c) 2026 Raphael Tobar, available under the [MIT License](LICENSE). Developed with AI assistance. MIT applies only to original contributions; it does not replace upstream rights, conditions, copyright notices, disclaimers, or patent terms.

## Code containing upstream contributions

- `surface_core.h` adapts MoonRay `PixelFilter.h`, `Sampling.ispc`, `ReferenceFrame.h` and `BsdfLambert.h`, copyright 2023–2024 DreamWorks Animation LLC. These portions remain under Apache-2.0; see [MOONRAY_LICENSE.txt](MOONRAY_LICENSE.txt). The adaptation combines a restricted shared CPU/CUDA camera/filter/Lambert implementation and preserves the upstream copyright notice.
- `async_adaptive.h` and the pixel error in `async_integrator.h` adapt MoonRay `rndr/adaptive/AdaptiveRegionTree.{h,cc}`, `AdaptiveRegions.cc`, `OverlappingRegions.h`, `ActivePixelMask.h` and the adaptive pass schedule of `RenderDriver.cc`, copyright 2023–2024 DreamWorks Animation LLC, under Apache-2.0; see [MOONRAY_LICENSE.txt](MOONRAY_LICENSE.txt). The error measure, region layout, split and stopping rules and pass schedule are MoonRay's; the summed-area table, the bisection for split points and the pass chain around them are original.
- The sine/cosine polynomial in `surface_core.h` uses ISPC 1.31 coefficients, copyright Intel Corporation, under BSD-3-Clause. See [ISPC_MATH_LICENSE.txt](ISPC_MATH_LICENSE.txt).
- `texture_core.h` adapts OpenImageIO 3.1.17.0 texture filtering and math. These portions and the reference sources in `vendor/oiio/` remain Apache-2.0, copyright Contributors to the OpenImageIO project. See [license](vendor/oiio/LICENSE.md) and [original source URLs and hashes](vendor/oiio/PROVENANCE.json). The adaptation implements the admitted filtering subset on CPU/CUDA with explicit residency misses.
- Philox and its known-answer vectors in `sample_stream.h` / `sample_fixture.h` are adapted from Random123, copyright 2010–2011 D. E. Shaw Research, under BSD-3-Clause. See [RANDOM123_LICENSE.txt](RANDOM123_LICENSE.txt). Original scheduling, identity, Sobol integration and other additions do not remove those conditions.

Keep these notices and license texts with redistributed source or binaries as their terms require. Source files containing upstream-derived code are not represented as exclusively MIT-licensed.

## External dependencies

MoonRay/scene_rdl2, Embree, OpenImageIO, NVIDIA CUDA/NVRTC/OptiX, and the Windows build dependencies retain their separate licenses. This source publication does not distribute their SDKs, runtime binaries, or a right to relicense them. Obtain required SDKs and dependencies under their own terms. It also does not relicense the rest of MoonRayForModo or the earlier architecture experiments.
