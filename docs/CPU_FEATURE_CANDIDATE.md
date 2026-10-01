# CPU compatibility candidate — unverified

Full Modo parity has **not** been achieved. This source checkpoint was written
at the user's request without running tests, building binaries, or installing
the changed kit. Python/XML/JSON syntax parsing is the only validation performed.
The installed CustomView kit remains the previously tested version.

The compatibility target is Modo scene features and controls with MoonRay's
rendering models. Pixel-for-pixel matching of Modo's renderer is not required.

## Follow-up source changes: texture groups and sequence recovery

- Nested texture-only groups with Normal group blending preserve their channel
  backdrop and composite at each group boundary with the group's opacity.
- Group-mask texture effects are consumed within that texture group. They do not
  mask sibling groups or replace a material stack's own mask. Common base-material
  ancestors stay in the material scope. Disabled ancestor groups are skipped in
  both direct and evaluated exports.
- Non-Normal group blends, opacity on whole-material groups, arbitrary layer
  masks, and groups spanning multiple base-material boundaries remain unsupported.
  This is partial Shader Tree translation, not complete layered-shader parity.
- Animation completion checks the expected output path before advancing a frame.
  Manifest write failures release the active sequence and preserve completed
  images. Starting a final still stops an active sequence; queued live updates do
  not replace animation work.
- Deferred tests were added to `tests/test_cpu_features.py` (textures group) and
  `tests/test_animation.py` (requires Modo Python/Qt). None were executed. The
  numerical group tests validate the chosen compositing rules; a Modo scene
  comparison is still needed to verify host semantics.

## Source implemented in this checkpoint

### Camera, motion, projections and release integrity (also unverified)

- Film Offset X/Y and render/camera pixel aspect now participate in film-gate
  conversion. Film-fit calculations use the physical output aspect. Native
  perspective/orthographic equations determine offset units and pixel-aspect
  compensation; Modo reference framing still needs validation. See Foundry's
  [camera controls](https://learn.foundry.com/modo/14.0/content/help/pages/rendering/camera_item.html)
  and [16.1 frame settings](https://learn.foundry.com/modo/16.1v8/content/help/pages/rendering/frame.html).
- Shutter samples match mesh/light/instance identities rather than array order.
  Duplicates, changed topology/assignments and missing instance transforms fail
  before modifying the snapshot. Animated perspective focal length uses the
  native blurrable focal attribute. Unsupported shutter-varying controls produce
  warnings and retain the frame-time value. Geometry arrays stay shared during
  motion assembly instead of being deep-copied.
- Cubic projection bakes a dominant-axis mapping per polygon, including locator
  transforms and axis selection, in both ordinary and evaluated exports.
  Degenerate faces fail explicitly. This is not smooth triplanar mapping; face
  orientation and seams require Modo scene comparisons.
- Spherical environment images accept the existing UV affine transform, origin
  rotation and repeat scaling through the layered bake. Disabled environments
  are skipped. The bake cache now includes output dimensions and a format version.
  Environment alpha, arbitrary tiling modes and nested groups remain incomplete.
- Deferred render reports fingerprint kit/native sources and runtime executables,
  libraries and shader modules before/after each run. Runtime packaging and
  installation require all five current feature reports; prior results cannot
  authorize changed binaries or sources. Packaging writes an atomic temporary
  archive and preserves an existing release on failure. This is a consistency
  gate, not evidence of complete compatibility or production readiness.
- Deferred numerical cases cover identity reordering, atomic failures, camera
  conversion, cubic faces and environment UV transforms. Render fixtures add
  film shift, non-square pixels and lens motion. `tests/test_validation_inputs.py`
  checks stale source/shader detection. None of these checks were executed.

### Subsurface controls and shared interiors (also unverified)

- Modo `subsColor` and `subsAmount` texture effects now route to MoonShine.
  Subsurface amount textures blend the scattering material against a surface-only
  copy; a zero base amount no longer disables a nonzero texture. Scattering
  distance still comes from the material's constant distance control.
- MoonShine material properties expose Normalized Diffusion, Dipole and Random
  Walk, subsurface normal-map evaluation, random-walk self-intersection handling,
  and anisotropy direction. These are scene-owned undoable commands, validated
  before writing. Host units, UI queries and persistence require deferred checks.
- Layered glass with a common active interior uses one absorption volume, with
  tint removed from each absorbing surface layer to avoid double attenuation.
  Scoped transmission-color group masks are retained for volume-map export.
  Fully overridden layers do not select the interior; conflicting active
  interiors produce an explicit export error. Mixed/overlapping interior volumes
  are still unsupported, and mapped volume coordinates remain unverified.
- Deferred material numerical/export cases, host-control checks and render
  fixtures were extended. No tests, renders, builds or installation were run.

### Texture and evaluated-geometry follow-up (also unverified)

- UV rotation now uses the origin, following Foundry's
  [Texture Locator reference](https://learn.foundry.com/modo/content/help/pages/shading_lighting/shader_items/texture_locator.html).
  Existing candidate exports with nonzero UV rotation will change accordingly.
- Independent horizontal and vertical Repeat, Edge, Mirror and Reset image
  modes are evaluated after coordinate interpolation. Reset contributes a
  coverage mask; it preserves the underlying layer outside the image domain.
  Repeat retains integer UDIM tile addressing. Non-Repeat modes on UDIM patterns
  remain explicitly unsupported. Filtering at wrap/reset seams is unverified.
- Image-channel selection translates Modo's `swizzling`/`rgba` controls and
  Use/Ignore/Alpha Only modes, including packed red/green/blue maps and channel
  inversions. Channel identifiers come from the installed 16.1v9 item definitions;
  behavior follows Foundry's
  [channel-swizzling reference](https://learn.foundry.com/modo/content/help/pages/shading_lighting/shader_items/channel_swizzling.html).
  Brightness, contrast and gamma adjustments remain unsupported.
- Evaluated meshes and replicas can now bake the existing planar, spherical and
  cylindrical locator projections per instance. Spherical/cylindrical seam
  correction operates per polygon. UV-only instances retain shared geometry;
  projected instances increase export memory/output size. Locator world/local
  flags, advanced projections, and exact host orientation still need completion.
- The texture and geometry numerical/export groups include new deferred cases.
  `tools/validate_cpu_feature_renders.py textures` now also writes asymmetric
  RGBA fixtures and compares tiling/channel responses. No tests or renders ran.
- Rebuild ModoTextureMap before using this checkpoint: new modes 5/6/7 and
  tile/component attributes are required by the Python exporter.

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
  channels are not reproduced. Current group masks cover material stacks and
  nested Normal texture groups; they are not a general Shader Tree evaluator.
- Colored dielectric F0, independent Modo Fresnel edge multipliers, SSS phase/
  depth behavior, dispersion, and layered or overlapping absorption volumes
  need further implementation. Different BSDFs are not appearance parity.
- Triplanar/camera projection, random UV transforms, native UDIM clip
  folders, transformed normal/bump tangent spaces and exact Modo procedural
  patterns remain incomplete.
- Replicator/material/crease fidelity is untested. Render Cache sampling still
  runs synchronously on the main thread; its full large-scene behavior is not
  established. Evaluated projections now expand affected replicas and need
  reference validation, including cubic orientation.
- Motion expands stable-identity instances to separately transformed meshes. It
  requires stable identities/topology. UVs, normals, shading parameters,
  lights other than transforms and environments are not motion sampled.
  Camera motion includes transforms and perspective focal length only.
- Orthographic scale uses target-distance/film/focal conversion and remains
  uncalibrated against Modo; a camera MRAY `ortho_width` value overrides it.
- Sky model, solar disc, ozone, multiple scattering, HDR orientation/exposure,
  scene color management and display transforms are not reference matched.
- Per-pass timeout does not cancel synchronous scene capture/texture preparation.
  Stress recovery, second-machine installation and release validation remain.

These are outstanding implementation and validation requirements, not merely
tests that can be skipped before claiming full parity.
