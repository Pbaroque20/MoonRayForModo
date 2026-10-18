# Native OIIO mip loading

`texture_oiio_loader.h` connects the experimental owned tile cache to real
OpenImageIO image decoding. It uses the same OIIO 3.1.17 DLLs as the frozen XPU
reference runtime. It is standalone: no installed kit, native shading path or
Modo scene was changed.

## Data contract

- Existing tiled mip levels are loaded on demand. Automatic tiling and mip
  generation are disabled, matching the native TextureSampler configuration.
- Keys identify the canonical UTF-8 file path, explicit content revision, OIIO/raw
  float interpretation, subimage, mip and tile coordinates. The loader preserves
  native channel count and produces owned, interleaved float32 texels.
- Mip dimensions come from `get_cache_dimensions`. In OIIO 3.x the old
  `imagespec(..., mip, ...)` overload ignores mip; using it would mis-size pages.
- Partial tiles are explicitly zero outside the image data window. The initial
  probe found that reading a whole padded tile through `ImageCache::get_pixels`
  can return nonblack padding where `TextureSystem::get_texels` returns black.
  The loader now clips the read rectangle and preserves the padded row stride.
- Source size/time are checked before and after loads. Detected changes fail
  without publishing new bytes under the old key. Registering a new revision
  invalidates OIIO's cached copy. Existing owned leases retain their old bytes.
  The caller still owns content revisioning: timestamp/size checks are not a
  content hash, a file watcher, or protection against same-stamp replacement.
  Stable/versioned backing files are required to reload evicted old revisions.
- No gamma, OCIO, channel expansion, filtering, wrap or alpha policy is implemented
  by this raw-page adapter. Existing shading retains those operations. File decode
  uses OIIO defaults, including its file-reader alpha association behavior.

Registration and reads are synchronous and confined to the loader's owning
thread. A future worker integration must create/use the loader there; this change
adds no blocking disk work to Modo. Registry entries, subimages, mip counts,
channels and maximum page bytes are bounded. OIIO has its own memory/open-file
settings in addition to the owned RAM/VRAM cache; its limit is not a whole-process
hard memory cap. Deep images, volumes, untiled/unmipped assets, oversized pages
and invalid coordinates/interpretations fail explicitly in this adapter.

## Validation

`tools/xpu2_texture_oiio_probe.py` builds an AVX1 executable, generates four small
textures, prepares their real mip chains with `maketx`, then compares cached pages
against a separate OIIO TextureSystem using MoonRay's texture-system settings.
Fixtures cover float32 RGBA/RG, half RGB and uint8 grayscale, non-power-of-two
sizes, partial edge tiles and the 1x1 mip tails. This run covers one subimage per
file; multi-subimage metadata is supported but has not been validated here.

The final GPU run passed:

- **37 exact page comparisons across 23 mip levels**, totaling 95,232 bytes.
- **2,215 exact base-level point lookups** at valid texel centers. These use the
  existing OIIO nearest sampler, not a new GPU sampler or filter implementation.
- **8 real RTX 3090 transfer consumers**, with 20,480 H2D bytes and exactly matching
  results. They use CUDA copies; no shading kernels are exercised.
- **35 RAM and 4 VRAM evictions** under 8,192-byte cache budgets. Peak staging was
  4,096 bytes. Clean eviction readback was zero; test verification read back
  20,480 bytes.
- Invalid keys/sizes/coordinates, missing and unsupported files, loader/registry
  limits, changed-file rejection, new revision loading and leased old data.

Source, preprocessed executable input, binaries, fixtures, tools, libraries and
runtime inventory are hashed. Compact evidence is `texture-oiio-20261017.json`;
full local logs are in `test-results/xpu2-texture-oiio-publish`.

```powershell
python tools/xpu2_texture_oiio_probe.py --source <read-only-toolchain-root> --runtime <frozen-XPU-runtime> --output <new-directory> --gpu
```

The first run exposed the padding mismatch described above. After correcting it,
the next run matched texels but failed a test coverage assertion because its RAM
budget was too large to evict anything. The final run tightened RAM/VRAM budgets
and passed both parity and eviction checks. No mismatch tolerance was relaxed.

A follow-up [CUDA point/bilinear filter experiment](TEXTURE_FILTER.md) now validates
base-level sampling and texture-space images. The rendered-scene and production
filtering gates below remain open.

## Remaining integration

This establishes raw mip data equivalence for these fixtures, **not filtered
rendered-image parity or a rendering/scene-load speedup**. GPU bilinear/bicubic,
anisotropic and derivative-dependent filtering, address modes, color/alpha policy,
UDIM resolution and scene-index revision binding still need implementation and
comparison against native XPU. Worker I/O/decode, native residency/context wiring
and priority-based prefetch also remain. Unsupported cases continue to require
the established native path before XPU2 can be enabled for rendering.
