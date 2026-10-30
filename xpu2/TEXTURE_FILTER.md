# CUDA point and bilinear texture filtering

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

This standalone experiment adds real CUDA sampling of the owned OIIO mip pages.
It does not replace native XPU texturing or enable an XPU2 renderer in Modo.

## Scope and execution

`texture_filter_cuda.cu` samples the cache's GPU page table using explicit FP32
operations. The tested subset is one supplied mip level (the base level here),
point or bilinear interpolation, and black/clamp/periodic/mirror addressing.
Inputs use zero-origin, full-data-window, ordinary pixel-center textures and
native channel counts from one through four. No hardware texture interpolation
unit is used, avoiding a separate hardware interpolation-precision assumption.

`texture_filter_probe.cc` acquires real GPU cache leases for every page in each
small test texture, uploads their address table and lookup requests, then launches
the filter kernel on the consumer stream. A completion fence protects page
residency until the kernel and its verification readback finish. Query tables and
verification buffers are separate test allocations, outside the texture budgets.
This first probe keeps each small texture fully resident; it is not a demand-paged
filtering benchmark or proof of asynchronous overlap.

Kernel statuses distinguish success, unsupported queries, invalid descriptors,
and absent pages. Missing data never becomes a successful black contribution.
Unknown modes/address modes, nonfinite or out-of-range UVs, unsupported channel
counts and truncated page tables are rejected. UVs outside [-8,8] are currently
unsupported; this finite diagnostic range is not a production wrap limit.
These statuses are tested but not yet wired to native XPU replay/fallback.

## Reference and boundary correction

The comparison uses the frozen native runtime's OIIO 3.1.17 TextureSystem, with
MoonRay's automatic-tiling/mipmap settings disabled. The four fixtures are the
previously validated float RGBA/RG, half RGB and uint8 grayscale textures. Each
gets both filters and four addressing modes, using a regular image grid, exact
and nearby texture/tile boundaries, and deterministic irregular UV coordinates.

The first run matched bilinear samples but found nearest-texel boundary errors.
The tagged [OIIO sample_closest implementation](https://github.com/AcademySoftwareFoundation/OpenImageIO/blob/v3.1.17.0/src/libtexture/texturesys.cpp)
chooses the lower texel at an exact half-pixel tie. Replacing the initially assumed
`floor(uv * resolution)` rule with that behavior removed the mismatch. No test
threshold was relaxed. This uses OIIO's behavior as the reference; it does not
change the native CPU sampler.

Before testing, gates were fixed at exact point results and maximum absolute
error 2e-6 for bilinear results on these [0,1] fixtures. The final run was stronger:
**all 587,776 compared components were exactly equal**.

## Final validation

- 32 filter/address/fixture combinations, 234,976 lookups.
- Point maximum error: 0. Bilinear maximum error: 0. Combined RMS error: 0.
- 32 fallback checks, including missing pages for both filters, malformed page
  tables, unsupported modes/channels/coordinates and NaN input.
- Independent saved EXR comparison: 96x64 RGBA, finite and nonconstant in every
  channel, zero differing pixels. Both images depict the same texture-space grid.
- CUDA cleanup errors: 0.

The image pair is **not a native MoonRay scene render**. It isolates filtered
texture values without geometry intersections, lighting, material evaluation,
path sampling, derivatives, or adaptive convergence.

The reproducible tool hashes sources, preprocessed C++, host binary, PTX, compiler,
NVRTC libraries, input fixtures and the frozen runtime inventory. Compact evidence
is `texture-filter-20261017.json`; full local output is in
`test-results/xpu2-texture-filter-image`.

```powershell
python tools/xpu2_texture_filter_probe.py --source <read-only-toolchain-root> --runtime <frozen-XPU-runtime> --fixtures <passed-OIIO-probe-directory> --output <new-directory>
```

## Remaining gates

Native defaults use derivative-dependent mip/anisotropic options, so this subset
cannot replace normal MoonRay lookups yet. Mip selection/blending, anisotropy,
bicubic filters, gradients, different S/T wrap modes, nonstandard windows/borders,
channel selection/fill/gray expansion, color and alpha policies, UDIMs and shader
integration remain. HDR/negative values and wider UV ranges need separate coverage.
Host eligibility checks must account for those semantics before submitting native
lookups to the GPU. Full rendered-scene comparisons and speed measurements follow;
no performance gain or general texture parity is claimed here.

The follow-up [residency-policy pressure test](TEXTURE_RESIDENCY.md) repeats these
comparisons after policy-driven GPU evictions under a reserved texture budget.
