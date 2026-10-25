# Patches to OpenMoonRay for the native Windows build

These patches are applied to OpenMoonRay's own source (`sources.json` names each repository, its commit and its
patch) to build MoonRay natively on Windows with MinGW-w64 (UCRT64) for the MoonRay for Modo plugin. Most of them
are portability changes. This file explains the ones whose reason is not obvious from the diff.

## `moonray.patch`: `lib/rendering/mcrt_common/Clock.h`, the heat map's clock on Windows

### What MoonRay does

The heat map output ("time per pixel", `RenderOutput` result `RESULT_HEAT_MAP`) adds up, for every pixel, the time
spent shading the rays that land in it. The time is measured by `mcrt_common::Clock`, an RAII wrapper around
`clock_gettime()`, started and stopped around each batch of work in `RayHandlers.cc`, `ShadeBundleHandler.cc`,
`XPURayHandlers.cc` and `RenderFramePasses.cc` (through `MCRT_COMMON_CLOCK_OPEN`). Its default clock is
`CLOCK_THREAD_CPUTIME_ID`, the calling thread's CPU time. The batches are short, typically tens to hundreds of
microseconds each.

### Why that fails on Windows

On Linux, `CLOCK_THREAD_CPUTIME_ID` is accurate to nanoseconds, so each short batch is measured as it is.

On Windows, a thread's CPU time is only advanced when the scheduler's clock interrupt fires, every 15.625 ms (1/64
second) by default. `clock_gettime(CLOCK_THREAD_CPUTIME_ID)`, as the MinGW-w64 winpthreads library provides it, reads
that tick-based count. So a batch that does not straddle a tick is measured as exactly 0, and one that does is
measured as one whole tick, 15.625 ms, whatever it really took.

In the heat map that gives almost nothing. Measured on the same 160 × 120 render of a lit triangle (16 samples per
pixel, scalar mode), before and after this patch:

| | Before (`CLOCK_THREAD_CPUTIME_ID`) | After (`CLOCK_MONOTONIC`) |
|---|---|---|
| Distinct values in the heat map | 3 | 6,812 |
| Pixels reading exactly 0 | 85.6% | 0% |
| Other pixels | exactly 0.015625 s or 0.03125 s (one or two ticks) | from 0.000148 s up, in fine steps |

Before the patch, the heat map is black with scattered white dots, which are the batches that happened to straddle a
tick. It shows where the clock ticked, not where the render spent its time.

### The change

On Windows only (`#ifdef _WIN32`), `Clock`'s default clock is `CLOCK_MONOTONIC`, which winpthreads backs with
`QueryPerformanceCounter`, a counter with sub-microsecond resolution. Other platforms keep
`CLOCK_THREAD_CPUTIME_ID`, unchanged. `Clock` is used only for the heat map, so nothing else is affected.

### What it changes in meaning, and what upstream might prefer

`CLOCK_MONOTONIC` measures elapsed time between start and stop on the same thread, not CPU time. The two differ only
when the thread is preempted or blocked inside a measured batch. In a render, where the render threads are busy
shading, that is rare, and the heat map's purpose (showing which pixels are expensive relative to others) is kept.

An exact Windows equivalent of thread CPU time at high resolution exists: `QueryThreadCycleTime`, which counts the
thread's CPU cycles. It would need a conversion from cycles to seconds and a Windows-specific code path in `Clock`.
If OpenMoonRay supports Windows upstream, that, or this patch's simpler monotonic clock, is needed for the heat map
to mean anything there.

### How it was checked

- The same scene was rendered before and after, in scalar and XPU modes, and the heat map channel compared (numbers
  above).
- Every other output is unchanged: the display filter check, and a toon scene compared between MoonRay and the
  plugin's own preview renderer, give the same results as before the patch.

## `moonray.patch`: toon materials on coarse smooth-shaded meshes (`MOONRAY_MODO_TOON_TERMINATOR`)

Applied by `tools/port_toon_terminator.py`. Only active when MoonRay is started with `MOONRAY_MODO_TOON_TERMINATOR=1`
(the plugin's preference, on by default); without it MoonRay renders exactly as its source does.

### What MoonRay does

On a smooth-shaded polygon mesh (`smooth_normal`, or a subdivision surface) MoonRay shades with the interpolated
normals, but treats the surface as its flat faces in two places:

- Light culling: for a reflection-only BSDF, light from behind the face's geometric normal is dropped before the lobe
  sees it (`PathIntegrator.cc`, the culling normal; `DistantLight.cc` and the other lights' `sample`;
  `BsdfSlice::getSurfaceFlags`). Every `shadow_terminator_fix` mode also fades light by the geometric normal
  (`BsdfSlice::computeShadowTerminatorFix`).
- Shadow rays start on the flat face (`isRayOccluded`), so near the terminator they hit the neighbouring faces.

### Why it shows with toon

A Lambertian lobe is close to black where the geometric and shading normals part, so the face-shaped cut is not seen.
`DwaToonMaterial`'s toon diffuse (`ToonBsdfLobe`) is lit to the edge of its ramp, so its lit band ends in steps, one
per face, smaller under subdivision but still there. `prevent_light_culling` removes the culling, but not the fade or
the self-shadowing.

![Four renders of the coarse torus: as MoonRay renders it, without light culling and fade, without shadows, and with shadow rays started further out](../../docs/images/toon-edges-why.png)

*The torus as MoonRay renders it (1); without light culling and the geometric-normal fade, still stepped (2); with shadows off, smooth (3); with shadow rays started 0.3 out, smooth (4). The steps come from shadow rays starting on the flat faces.*

### The change

1. The toon diffuse lobe is made spherical, as `prevent_light_culling` makes it, and cuts light off by its own shading
   normal instead of being faded by the geometric one (`BsdfBuilder`, `BsdfToon`, scalar and ISPC; the ISPC side reads
   the switch from a global set once from C++, which assumes one ISPC target, as this build has).
2. At a hit on `DwaToonMaterial`, the triangle, quad and subdivision meshes record how far the smooth surface the
   vertex normals describe lies above the flat face (Hanika, "Hacking the Shadow Terminator", Ray Tracing Gems II,
   2021): `Intersection::mModoSmoothOffset`, a new field in the structure's existing padding, so its size and the
   C++/ISPC layout check are unchanged. Shadow rays toward a light near the terminator start from there: fully when the
   light is at or behind the face, fading out by the time it is 0.1 (in cosine) above it
   (`PathIntegratorMultiSampler.cc` and `.ispc`). Other materials record nothing. Instanced copies are left as they are.

### How it was checked

A torus of 24 × 12 quads with `DwaToonMaterial` under a low distant light (`test-results/issue-129/make_repro.py`):
stepped without the variable, smooth with it, in scalar, vector and XPU modes. The same scene with `DwaBaseMaterial`
renders identically with the variable on and off in scalar mode, and within the run-to-run variation of vector and XPU
modes (two renders with it off differ as much).

![A coarse and a subdivided toon torus in MoonRay, each with the switch off and on](../../docs/images/toon-edges-subdivided.png)

*Coarse and subdivided, with the switch off (left) and on (right). Subdivision makes the steps smaller without removing them.*

![A close-up of the lit band, stepped with the switch off and smooth with it on](../../docs/images/toon-edges-closeup.png)

*Close up on the coarse torus.*

## `moonray.patch`: a toon material's albedo output (`MOONRAY_MODO_TOON_ALBEDO`)

Applied by `tools/port_toon_terminator.py`, behind a switch of its own (the plugin's preference, on by default).

### What MoonRay does

The `albedo` material AOV (`Aov.cc` and `Aov.ispc`, `computeAlbedo`) averages `f / pdf` over each lobe's BSDF samples.
For a lobe whose `f` carries the cosine and whose samples are drawn by the cosine, that is its albedo.

### Why it fails for toon

`ToonBsdfLobe` is deliberately flat: its `f` is `albedo × ramp / 2π`, with no cosine, but it is sampled by the
cosine (`pdf = cos / π`). Each sample is then `albedo × ramp / (2 cos)`, which grows without bound towards grazing
directions. On a toon torus at 4 samples a pixel the AOV reaches 202,000 in scalar mode (its true values are under 1).
The denoisers take this AOV as their albedo guide; a guide full of bright specks is read as detail, and the denoised
toon surface comes out as noisy as it was rendered. Clamping or median-filtering the guide afterwards does not recover
it.

### The change

With the switch on, a `ToonBsdfLobe` (`BSDF_LOBE_TOON` in ISPC) contributes its own `albedo()`, the Lambertian
albedo it inherits, the same for every sample. Other lobes are unchanged.

### How it was checked

The toon torus of `test-results/issue-129/make_repro.py` with the albedo and normal guides: the guide stays within the
material's colour (0.9, 0.5, 0.3) in scalar and vector modes, and Open Image Denoise then cleans the toon surface as
it does a `DwaBaseMaterial` one (`test-results/issue-129/check_albedo.py`).

![A toon render, denoised with the switch off and on](../../docs/images/toon-denoise.png)

*The render, then denoised with the switch off (as noisy as rendered: the albedo guide is full of specks) and on.*

## `mcrt_denoise.patch`: the denoiser cleans its guides first (`MOONRAY_MODO_DENOISE_CLEAN_GUIDES`)

Applied by `tools/port_denoise_overrides.py`, behind the preference "Denoiser cleans its guides first", on by default.
The plugin starts `denoise.exe` with the same environment as MoonRay, so the switch reaches it.

### What MoonRay does

`OIDNDenoiserImpl` hands Open Image Denoise the albedo and normal guides as rendered, and leaves `cleanAux` off: the
guides are taken to be noisy, and the denoiser trusts them less.

### Why that fails

At a preview's sample counts the guides are close to clean (a material's albedo and a surface's normal change little
from sample to sample), but trusted less, they help less: on textured, bumpy and see-through surfaces the denoiser
keeps more of the render's noise and blurs what the guides would have kept. Open Image Denoise's own documentation
advises cleaning the guides with filters of their own and setting `cleanAux` for the best quality.

### The change

With the switch on, each guide is cleaned first by an `RT` filter of its own, in place, and the beauty's filter is
told the guides are clean (`cleanAux`). Off, the guides are used as rendered. OptiX has no such mode: with it the switch
changes nothing.

### How it was checked

MoonRay renders at 16 samples a pixel, denoised by `denoise.exe -mode oidn_cpu` as the plugin runs it, against the
same scenes at 1,024 (8-bit RMS of the displayed picture): a translucent, scaled dragon on a floor 3.58 to 3.27 (4.77
to 4.36 a stop brighter); a glass, a mirror and a skin ball 2.30 to 1.67 where their highlights show, level (2.17,
2.21) at an exposure that clips them. Tried and left out on the same pictures: pulling fireflies down before
denoising helped only by flattening bright highlights' edges, which would dim a thin rim light too; giving OptiX's HDR
model the picture's brightness (`optixDenoiserComputeIntensity`), and OptiX's AOV model, each gave a picture identical to
MoonRay's own (OptiX measures the brightness itself when it is not given one).

## `moonray.patch`: volumes in Cryptomatte (`MOONRAY_MODO_CRYPTO_VOLUMES`)

Applied by `tools/port_crypto_volumes.py`, behind a switch of its own (the plugin's preference, on by default).

### What MoonRay does

Cryptomatte records the surface a camera ray, or a presence continuation of it, hits (`PathIntegrator.cc`,
`computeRadianceRecurse0`; in vector and XPU modes `ShadeBundleHandler.cc` and `Film.cc`), at the ray's full pixel
weight. Volumes on the way are never recorded, and `computeRadianceVolume` is called with `cryptomatteFlags = 0`.

### Why that fails

A cloud, smoke or fog has no matte. And a surface behind a thick volume has as much coverage as one in the clear, so
where a volume lies in front of a surface the coverages in a pixel add up to more than the volume and surface hide
together; where it lies in front of nothing they add up to less than the pixel's alpha (by 0.60 in the test below).

### The change

- As the frame starts (`PathIntegrator::update`), each layer assignment that holds a volume shader is mapped to the
  Cryptomatte IDs on its geometry's `primitive_attributes` UserData: the first `deep_id_attribute_names` entry, and
  the plugin's `modo_material_id` and `modo_asset_id`. `VdbGeometry` declares `primitive_attributes` for this; it reads
  nothing else from it (`ModoCryptoVolumes.h`).
- At the end of `computeRadianceVolume` for a camera ray (depth 0, lobe type 0; scalar, vector and XPU all march
  volumes there), the `VolumeProperties` steps of the march are walked: each step's share of the opacity, by luminance
  of its extinction as MoonRay's own volume surface depth has it, goes to the step's assignment (the densest volume in
  it). Each volume is recorded once per ray with `addSampleVector` (which locks the pixel), with that share times the
  ray's pixel weight as coverage, at the depth its share is centred on, facing the camera, with the volume's light as
  its beauty. A ray stopped by the transmittance threshold gives what is left to the last volume.
- What shows through the volumes so far is kept for the surface the ray then hits, and for presence surfaces after it:
  per thread for a scalar camera sample, and in `CryptomatteData` for vector and XPU, where `mPresenceDepth` gives up
  16 bits to a 16-bit `mVolumeFront` (the struct is at its 64-byte bound). Those surfaces are recorded at their weight
  times it, and a presence continuation ray inherits it.

### How it was checked

A VDB ball of fog with a hole, in front of two boxes on a floor, with an object Cryptomatte and with all three
categories, rendered in scalar, vector and XPU modes (`test-results/crypto-volumes`): with the switch on, every
pixel's coverage equals its alpha (to 1e-4) in every category and mode, and the fog's matte has the ball's shape and
hole; with the switch off, the output is MoonRay's (no fog matte; coverage short of alpha by up to 0.60).

A partly see-through pane behind the fog shows a separate issue in MoonRay's alpha, not changed here: past a presence
surface, the alpha (`transparency = (1 - presence) * presenceTransparency` in `computeRadianceRecurse0`) leaves out the
volume in front, so with fog of 0.60 in front of a 0.4 pane against the sky MoonRay's alpha is 0.40 where the fog and
pane hide 0.76. The coverage is 0.76.

![A ball of fog in front of two boxes, the fog's matte, and the boxes' matte without and with the switch](../../docs/images/crypto-volumes.png)

*The check scene at 16 samples a pixel (vector): the render, the fog's own matte, and the boxes' matte with the switch off (bottom left, solid behind the fog) and on (bottom right, faded where the fog hides the box).*

## `moonray.patch`: fog in front of a see-through surface in alpha (`MOONRAY_MODO_FOG_ALPHA`)

Applied by `tools/port_fog_alpha.py`, behind a switch of its own (the plugin's preference, on by default).

### What MoonRay does

In scalar mode, `computeRadiancePresence` sets a presence surface's transparency to
`(1 - presence) * presenceTransparency`. The cutout branch of `computeRadianceRecurse0` just above multiplies by the
volume's transmittance alpha ("We also multiply by the volume's transmittanceAlpha"); the presence branch does not. In
vector and XPU modes a camera path's alpha is the sum of its entries (`fillBundledRadiance`; the miss branches of
`RayHandlers.cc` and `XPURayHandlers.cc`): a surface after a volume counts its pixel weight in full, and the volume's
opacity is counted only for a ray that misses.

### Why that fails

Where the fog's own opacity is not counted, fog in front of a presence surface is missing from alpha. Fog hiding 0.60
in front of a pane of presence 0.4 against the sky gives an alpha of 0.40, where the two hide 0.60 + 0.40 x 0.4 = 0.76.
The picture composites thinner than it renders.

### The change

- Scalar: the presence transparency is multiplied by `reduceTransparency(vt.mTransmittanceAlpha)`, as the cutout's is.
- Vector and XPU: `PathVertex` gains `modoFogFront` (1 at the camera: how much of what lies behind the volumes passed
  so far shows through) and `modoFogPending` (0 at the camera: those volumes' opacity not yet counted). RayState's ISPC
  padding gives up the 8 bytes (`RAY_STATE_MEMBERS_PAD` 28 to 20, 76 to 68). After a camera ray's volumes are marched,
  `pending += pathPixelWeight * front * (1 - transmittance)` and `front *= transmittance`. A camera ray's alpha entry is
  `pending + front * MoonRay's alpha`; a miss, a hit light or a hit on geometry with no material counts `pending`
  alone. A presence continuation keeps `pending` only when the surface it leaves has presence 0 (it is not shaded and
  so counts nothing). A cutout counts `pending` and nothing behind it.
- Without the switch the two floats stay 1 and 0, and every alpha is MoonRay's.

### How it was checked

The fog ball of the Cryptomatte check with a pane of presence 0.4 between it and the boxes
(`test-results/fog-alpha`), scalar, vector and XPU: with the switch on, every pixel's alpha equals the sum of its
Cryptomatte coverages (0.0000 worst difference; 0.76 at the pane against the sky); off, MoonRay's (0.36 worst). Colour
is unchanged: identical in scalar, and in vector within the run-to-run noise of two renders with the switch off. In a
scene without a presence surface the alpha is unchanged.

![A pane behind fog against the sky, with its alpha as MoonRay makes it and with the switch on](../../docs/images/fog-alpha.png)

*A pane of presence 0.4 with fog in front of it and sky behind (left); its alpha with the switch off, the pane alone (middle), and on, the fog counted in front of the pane (right). 16 samples a pixel, scalar.*

## `moonray.patch`: each Cryptomatte sample counted once (`MOONRAY_MODO_CRYPTO_ONCE`)

Applied by `tools/port_crypto_once.py`, behind a switch of its own (the plugin's preference, on by default).

### What MoonRay does

In vector and XPU modes a camera path reaches the film as several radiance entries, which film threads can add at once.
`Film::addSampleBundleHandlerHelper` gives the path's surface its Cryptomatte coverage with the first of them: it reads
the path's `CryptomatteData::mIsFirstSample`, adds the sample, then clears the flag.

### Why that fails

Two threads that read the flag before either clears it both add the coverage. Now and then every sample of a pixel is
counted twice, and its mattes add up to twice its alpha (coverage 2.0 for an opaque surface).

### The change

With the switch on, the flag is read and cleared in one atomic exchange (`modoTakeFirstSample`, `ModoCryptoOnce.h`),
so one entry alone adds the coverage. Off, MoonRay's read then clear.

### How it was checked

Vector renders of the fog Cryptomatte scene at 480 x 270 and one sample a pixel, counting pixels whose coverage goes
over 1: 2 of 16 renders without this switch had one (one with fog in Cryptomatte on, one with it off); then 2 of 54
off and none of 54 on. A rare race is not proven gone by this, but the exchange leaves no
window for it.

## `moonray.patch`: a stopped render finishing the tiles in hand (Stop finishes the tiles in hand)

Applied by `tools/port_drain.py`. The plugin's preference "Stop finishes the tiles in hand" (on by default) decides
whether the plugin asks for it; off, MoonRay is stopped as its own source stops it.

### What MoonRay does

A render can be stopped at once (cancelled), which leaves the samples then in flight unpaid: the tiles the workers
were on stay dark or coarse in the picture. Or it can be stopped at the end of a pass, which may be most of the render
away.

### Why that fails for a preview

When a preview is stopped by hand, or by Smart Render once its picture is clean enough, the picture is kept and
denoised. Stopped at once, it has dark and coarse patches where the hard tiles were, which the denoiser smears.

### The change

`RenderDriver::requestDrain` (reached through `RenderContext::requestDrain`, which the plugin's persistent session
calls when asked): the workers take no new tiles, the tiles in hand are rendered to the end, the queues are drained as
at the end of any pass, and the frame ends there as a finished one, every buffer written. It does nothing unless asked.

### How it was checked

A preview stopped part way with the switch on and with it off: on, the session is asked to drain and the frame ends as
a finished one; off, the plugin does not ask, and stops as MoonRay's own stop does
(`tools/probe_drain_override.py`).

## `moonray.patch`: UsdPreviewSurface's specular colour (`MOONRAY_MODO_USD_SPECULAR`)

Applied by `tools/port_source_switches.py`, behind a switch of its own (the plugin's preference "UsdPreviewSurface
specular colour", on by default).

### What MoonRay does

With `useSpecularWorkflow` set, UsdPreviewSurface adds no highlight at all: its source says "We can't support this until
we implement Schlick fresnel so do nothing for now."

### Why that fails

A material made in the specular workflow, as USD and MaterialX assets often are, renders as if it had no reflection.

### The change

`BsdfBuilder::addSchlickReflection` (a GGX lobe, or a mirror when the roughness is 0, with Schlick's Fresnel from the
`specularColor` at normal incidence) is added in that workflow, in the scalar and vector code. Off, nothing is added.

### How it was checked

A ball in the specular workflow under a rectangle light, rendered with the switch on and off: on, it has its highlight;
off, none (mean difference 47 across the picture).

## `moonray.patch`: an image without alpha reads as opaque (`MOONRAY_MODO_OPAQUE_ALPHA`)

Applied by `tools/port_source_switches.py`, behind the preference "Images without alpha are opaque", on by default.

### What MoonRay does

`BasicTexture`, and `UdimTexture` for an image named with `<UDIM>`, sample through OpenImageIO, whose fill value for a
channel the image does not have is 0. An image with three channels has an alpha of 0 wherever a material reads it.

### Why that fails

An `ImageMap` with `alpha_only`, or anything taking a texture's alpha as a mask or presence, reads an ordinary RGB image as
fully transparent. The plugin's image layers also recover unassociated colour by dividing by the image's alpha
(`ModoTextureMap` blend 5), so a colour read through such an image is multiplied by a million: a `<UDIM>` tile set lit a
whole scene white until `UdimTexture` had the change too.

### The change

The fill is 1 for every quality level of the texture, in `BasicTexture` and in every tile of a `UdimTexture`: a missing
alpha channel is opaque, as `ImageMap`'s alpha-only mode documents. Off, OpenImageIO's 0.

### How it was checked

An `ImageMap` with `alpha_only` on a three-channel texture as a ball's albedo: white with the switch on, black with it off.

## `moonshine.patch`: rough glass under a mirror smooth surface (`MOONRAY_MODO_TRANSMISSION_ROUGHNESS`)

Applied by `tools/port_source_switches.py`, behind the preference "Rough glass under a smooth surface", on by default.

### What MoonRay does

`DwaBaseLayerable::createLobes` builds a mirror reflection and mirror refraction pair whenever the surface roughness is 0,
even when `use_independent_transmission_roughness` gives the transmission a roughness of its own.

### Why that fails

Frosted glass under a polished surface (roughness 0, transmission roughness above 0) refracts as clear glass.

### The change

The mirror pair is used only when the transmission is also mirror smooth, or there is none; otherwise the microfacet
lobes, which take the transmission roughness. Off, MoonRay's test on the surface roughness alone.

### How it was checked

A smooth glass ball with a transmission roughness of 0.6 in front of a small bright light: with the switch on the light
seen through the ball is blurred, off it is sharp (mean difference 22).

## `moonray.patch`: Auto renders on the graphics card first (`MOONRAY_MODO_AUTO_XPU`)

Applied by `tools/port_source_switches.py`, behind the preference "Auto renders on the graphics card first", on by
default.

### What MoonRay does

`RenderContext::startFrame` starts the Auto execution mode in vector mode. The XPU branch is in the source, commented out
("Uncomment the following to have AUTO mode start with XPU").

### Why the plugin changes it

On a machine with a supported graphics card, Auto then renders on it, which is much quicker; a scene with something XPU
does not support still falls back (`allowUnsupportedXPUFeatures` is false).

### The change

Upstream's own branch, taken with the switch on. Off, Auto starts in vector mode as MoonRay's source does.

### How it was checked

The same scene in Auto: MoonRay's log says "Executing an XPU render since execution mode was set to auto." with the switch
on, and "Executing a vectorized render since execution mode was set to auto." with it off.

## `moonshine.patch`: toon lines apart from the shading (`output_mode`)

A new attribute of `ToonDisplayFilter`, behind the preference "Toon lines apart from the shading", on by default; with it
off the plugin does not write the attribute and the filter renders as MoonRay's own.

### What MoonRay does

`ToonDisplayFilter` multiplies its cel shading by its ink, `result * min(inkD, inkN)`: the lines and the shading come out
as one picture.

### Why the plugin changes it

Artists composite toon lines over the shading themselves (a colour, a width, a different weight per shot), which needs the
lines as a picture of their own.

### The change

`output_mode`: 0, shading and lines (MoonRay's); 1, the lines alone, as much white as there is ink on black; 2, the shading
without its lines. Two Toon filters, one of each, are two buffers of the preview and two channels of the EXR.

### How it was checked

Built (`ninja bin/ToonDisplayFilter.so bin/ToonDisplayFilter.so.proxy` in `build/native-renderer-avx`); not yet rendered.

## `cl1-pool-scale.patch`: a larger store for rays in flight (no switch)

`ThreadLocalState.cc` gives each thread four times MoonRay's store of CacheLine1 items, about 4 GB of address space at 16
threads, touched only as it is used. In XPU mode, with many render outputs and adaptive sampling, MoonRay's own size runs
out and the render stops with "timed out whilst trying to allocate a CacheLine1". It changes no picture, so it is not a
MoonRay Source Override; `MOONRAY_MODO_CL1_POOL_SCALE` sets another multiple, from 1 (MoonRay's own) to 8.

