# CPU production-readiness work

This is an implementation and verification checklist, not a compatibility claim.
Unchecked items remain required by the requested CPU work.

## Materials
- [x] Standard reflection lobe, strength/color/roughness and texture controls
- [ ] Full Modo specular/reflection Fresnel parity
- [ ] Layered BSDFs and masks
- [x] MoonShine anisotropy strength with native material properties
- [ ] Anisotropy texture/tangent controls and standard-material parity
- [ ] Subsurface scattering
- [ ] Distance-based glass absorption

## Textures
- [ ] Multiple UV sets per material
- [ ] UV transforms and additional projections
- [ ] UDIMs
- [ ] Broader Shader Tree blending

## Environments
- [ ] Reference-render calibration of orientation, brightness and gradients
- [ ] Environment layering
- [ ] Physical daylight

## Geometry
- [x] Modo-evaluated displacement in the experimental evaluated-geometry mode
- [ ] Subdivision creases
- [ ] Render Cache/evaluated geometry fidelity
  - [x] Evaluated tessellation, nonuniform scale/rotation, per-corner normals and named UVs
  - [x] Shared mesh instances and hidden source geometry
  - [x] Actual MoonRay renders of evaluated UVs and distinct instance materials
  - [ ] Crease and replicator fixtures, large-scene memory/performance checks
- [ ] Replicators
- [ ] Instance material overrides
  - [x] Mesh/mesh-instance item masks, including disabled-mask handling
  - [ ] Group/part masks, layered BSDF compositing and broader instance cases

## Render workflow
- [x] Render regions with full-frame output and scene-owned panel controls
- [ ] Translate Modo's own render-region selection
- [ ] Animation output
- [ ] Motion blur
- [ ] Orthographic cameras
- [x] Perspective depth of field: focus distance, f-stop, blade count/rotation
- [ ] Modo bokeh/iris-bias reference parity
- [ ] Native Render View integration
  - Experimental C++ external-render adapter loads in Modo 16.1v9 and transfers
    progressive images into PView. Geometry/color display, docking and shutdown
    validation remain; PView is distinct from the legacy final Render View.
  - Kit candidate includes startup/menu wiring and early shutdown handling.
    Automated PView tests still expose activation/buffer failures and a shutdown
    access violation. A transferred-frame counter alone is not a passing test:
    installation now also requires nonblack saved pixels and clean process exit
    for the exact adapter binary. The normal installed kit has not been replaced.
  - The user confirmed the isolated white-triangle fixture stays blank. Its
    source EXR contains the triangle, but PView rejects `WriteBegin` with
    `0x80000000`; frame transfer remains unverified. Zero-initialized buffer
    arguments, staged viewport activation, and a synchronous worker-thread
    experiment did not resolve it. The worker experiment was reverted.
    Pending transfers now expose the diagnostic after ten seconds, and cannot
    report completion before the host accepts the image.

## Production validation
- [ ] Large-scene memory and performance tests
- [ ] Cancellation and recovery under load
- [ ] Color-management reference tests
- [ ] Reproducible packaging and clean installation
- [ ] Installation and rendering on a second Windows machine

No second Windows computer is available. A separate local Modo profile can test
startup isolation but cannot establish second-machine compatibility.

Already verified foundations include native AVX1 CPU rendering, named-UV images,
normal/bump maps, basic texture layers, mesh instances, Moonshine DwaBase,
amount/dissolve maps, basic environment translation and a docked custom preview.
These do not establish full scene parity or production readiness.

## Current evaluated-geometry candidate

The Render Setup surface list now contains **Modo evaluated geometry (experimental)**.
This source candidate requires the supplied-SDK native adapter and a Modo restart.
It exports Modo's render tessellation/displacement instead of applying a second
MoonRay subdivision step; MoonRay per-object subdivision overrides are bypassed.
Density follows Modo's render settings and can be expensive. Full scene sampling
still runs synchronously on Modo's main thread and is not large-scene ready.

The adapter uses borrowed-reference ownership for Render Cache surfaces, segments
and shader items, as required by the SDK's User helpers. Tests caught and corrected
both double scaling/transposed transforms and premature release of instance data.
Material membership still needs explicit item-mask filtering in Modo 16.1; taking
every returned shader layer would incorrectly paint source and instance alike.

Reproducible checks: `probe_render_cache.py`, `probe_evaluated_details.py`,
`probe_instance_material.py` through `run_script_probe.py`, followed by
`validate_evaluated.py`. The regular `run_host_probe.py` still passes all 25 tests,
including its six Qt renderer lifecycle tests, plus scene/Undo checks.
