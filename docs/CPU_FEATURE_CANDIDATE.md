# CPU compatibility candidate — unverified

Full Modo parity has **not** been achieved. This source checkpoint was written
at the user's request without running tests, building binaries, or installing
the changed kit. Python/XML/JSON syntax parsing is the only validation performed.
The installed CustomView kit remains the previously tested version.

## Source implemented in this checkpoint

- Ordered DwaLayer material stacks, per-layer opacity and group-mask map input.
- MoonShine subsurface radius/color/amount; partial amounts blend surface diffuse
  and SSS. Standard anisotropic/subsurface materials use MoonShine automatically.
- Dielectric reflection IOR derived from standard-material average F0, separate
  transmission IOR, anisotropy maps and tangent-angle data.
- Constant or mapped Beer–Lambert absorption using a BaseVolume assignment.
- Named face-varying UV sets; per-layer affine transforms, rotation and repeats.
- Planar, spherical and cylindrical locator projections baked at polygon corners.
  World-projected instances expand when they need different coordinates.
- Explicit `<UDIM>` still-image filename patterns and per-tile conversion/cache
  invalidation. Native Modo UDIM clip-folder item discovery remains unsupported.
- Difference, darken, lighten, overlay, hard-light, exclusion and divide blends,
  alongside the existing normal/multiply/add/subtract/screen modes.
- Standalone MoonRayGeometry adapter with no ExternalRender registration. Render
  Cache handles evaluated tessellation/displacement and generated replicas.
- Evaluated part masks and group-locator hierarchy targets; stable instance IDs.
- Crease serialization for explicit snapshot crease pairs/sharpness. Direct
  extraction of Modo edge crease weights is not implemented; evaluated geometry
  relies on Modo's own tessellation to retain them.
- Cached linear environment-layer composition with per-image orientation.
- An approximate single-scattering physical sky driven by a Sun Light. This is
  explicitly **not Modo's daylight model** and cannot establish appearance parity.
- Orthographic output, normalized Modo render-region translation, frame-at-a-time
  animation queue and two-endpoint transform/deformation/instance motion output.
- Time restoration after frame capture; output collision protection and a
  completed-frame manifest; per-render watchdog; deterministic ZIP timestamps,
  permissions and file hashes.
- Streaming geometry JSON to a temporary file and unloading exported segments,
  plus streaming snapshot hashing to reduce duplicate whole-scene buffers.

## Build dependencies before any future validation

Rebuild and stage the native CPU runtime with the updated ModoTextureMap and
DwaLayerMaterial targets. Staging now includes oiiotool for HDR environment
conversion. Do not mix the new Python translator with the old texture-map DSO.

`tools/build_modo_bridge.py --geometry-only --skip-tests` builds
`build/modo-bridge/MoonRayGeometry.lx` without running tests. For host checks,
place that candidate in the isolated kit's `bin` directory. Do not reintroduce
the experimental MoonRayPreview adapter into the normal kit.

## Deferred scripts — none run in this checkpoint

Use the Modo 16.1v9 bundled Python environment for Qt-dependent scripts.

1. `tools/test_cpu_feature.py materials|textures|geometry|environments|rendering|all`
   checks numerical behavior and scene serialization. It does not launch Modo or
   MoonRay and cannot prove renderer compatibility.
2. `tools/validate_cpu_feature_renders.py materials|textures|geometry|environments|rendering`
   renders controlled fixtures and checks meaningful image changes. Images and
   logs stay in `test-results/cpu-features`. These are response tests, not visual
   equivalence tests.
3. `tools/run_script_probe.py probe_cpu_feature_channels.py` checks actual Modo
   material/camera/region channels and time restoration in an isolated headless
   16.1v9 process.
4. `tools/run_script_probe.py probe_cpu_reliability.py` checks Qt lifecycle and
   timeout behavior. It does not replace large-scene load testing.
5. `tools/compare_render_reference.py moonray.exr modo.exr --rmse-limit VALUE --output report.json`
   compares linear RGB reference images with a caller-specified tolerance.
   Camera, lighting, exposure, AOV and color space must match. One passing pair
   establishes nothing about unrelated scenes.

## Remaining parity gaps

- Arbitrarily nested Shader Tree groups, group blend semantics, layer masks,
  non-material selection masks, broader procedural/node shaders and all effect
  channels are not reproduced. Current group masks cover only the material-stack
  path; they are not a general Shader Tree evaluator.
- Colored dielectric F0, independent Modo Fresnel edge multipliers, SSS phase/
  depth behavior, dispersion, and layered or overlapping absorption volumes
  need further implementation. Different BSDFs are not appearance parity.
- Cubic/triplanar/camera projection, random UV transforms, native UDIM clip
  folders, transformed normal/bump tangent spaces and exact Modo procedural
  patterns remain incomplete.
- Replicator/material/crease fidelity is untested. Render Cache sampling still
  runs synchronously on the main thread; its full large-scene behavior is not
  established. Named evaluated projections other than UV are rejected.
- Motion expands stable-identity instances to separately transformed meshes. It
  requires stable identities/topology. UVs, normals, shading parameters,
  lights other than transforms and environments are not motion sampled.
- Orthographic scale uses target-distance/film/focal conversion and remains
  uncalibrated against Modo; a camera MRAY `ortho_width` value overrides it.
- Sky model, solar disc, ozone, multiple scattering, HDR orientation/exposure,
  scene color management and display transforms are not reference matched.
- Per-pass timeout does not cancel synchronous scene capture/texture preparation.
  Stress recovery, second-machine installation and release validation remain.

These are outstanding implementation and validation requirements, not merely
tests that can be skipped before claiming full parity.
