# Local validation — 2026-09-30

Test machine: Windows, Intel Core i7-4930K (AVX1, no AVX2), Modo 16.1v9.

- Native renderer: seven component tests pass, including AVX/ISPC mask ABI,
  64-bit codecs, Windows platform services, scene parsing and Embree intersection.
- Real scalar and AVX vectorized image renders succeed and exit normally.
  Invalid output paths fail promptly without hanging during DLL shutdown.
- Qt renderer: real cancellation, replacement image delivery and cleanup pass.
- Installed graphical Modo: a visible preview renders; moving a test mesh triggers
  live polling and a changed image without manually pressing Preview.
  The updated installed kit also passes all five menu-to-tab dispatch checks.
  UI accessibility confirms the MoonRay menu and object controls. Screenshot
  capture timed out, so pixel-level layout inspection remains unverified.
- Shadow investigation: the reported coarse sphere reproduces the stepped
  light/shadow boundary. Shadow-terminator compensation alone does not remove it.
  Catmull-Clark subdivision at resolution 8 removes the large polygon-shaped steps.
- Updated exporter: both Modo SUBD and Pixar PSUB faces are recognized inside
  Modo 16.1v9. Preview subdivision controls capture the expected mesh settings.
- All 25 plugin tests pass inside an isolated Modo 16.1v9 process, which exits 0.
- Authored UV and vertex-normal maps export with the expected face-corner values.
- Native object commands execute, query and undo. Scene and object settings
  survive saving and reopening an LXO in the isolated profile.
- A real native spotlight render writes 26 float EXR channels: beauty plus all
  the original ten AOV choices, with finite pixel values. Shared mesh material parts
  render with separate colors. `tools/validate_aovs.py` reproduces this check.
- Image-texture fixture: a Modo image layer exports its selected named UV set,
  converts sRGB into a tiled linear texture, and produces the expected red/green
  regions in an actual MoonRay render. Editing the source invalidates the cache
  and swaps those rendered regions. Missing UVs and layer opacity are checked
  explicitly. Scripts: `probe_image_textures.py`, `validate_textures.py`.
- Glass: standard Modo transparency amount/color, IOR, reflection/transparency
  roughness and dissolve channels reach the exported material. Native renders
  verify clear, tinted, frosted, partially transmitting and dissolved spheres.
  IOR 1.5 bends the striped background; IOR 1 matches the dissolved reference.
  Clear scalar/AVX pixel error averages 0.033/255; noisy frosted renders agree
  within 1.579/255 using 8x8 block means. A separate transmission EXR pass contains finite,
  nonzero pixels. `test-results/glass/report.json` records shader checksums.
- The Qt live-preview controller renders glass, cancels an obsolete request,
  delivers only the replacement image and cleans up its temporary files:
  `test-results/glass-live-process/report.json`. This update was not reloaded
  into the user's already-open graphical Modo session; restart it after installation.

Detailed machine-local reports and rendered comparisons are under `test-results/`
and build logs under `build/`; both are excluded from Git. These checks do not
establish full production scene compatibility or upstream regression coverage.

The source repository excludes compiled runtimes, downloaded dependencies,
upstream checkouts, toolchains, user scenes and Modo profiles. The native port's
patches, pinned source revisions, build configuration and scripts are included.

## Surface, material and docking update

- `validate_surface_updates.py`: real scalar/AVX renders compare neutral and tilted
  tangent normals, flat/ramp bump maps, image alpha, ordered texture layers,
  checker and approximate fractal noise. Moonshine normals are also exercised.
  Shared instances match explicit transformed copies, including material parts.
- `probe_surface_updates.py`: inside Modo 16.1v9, checks named UVs, raw normal-map
  color, bump distance, Shader Tree layer order, disabled layers, shared instances
  and an explicitly visible instance with a hidden source.
- `validate_glass.py --moonshine`: the actual DwaBaseMaterial passes clear/frosted
  scalar/AVX comparisons, IOR changes, tint, transmission/presence separation and
  finite nonzero transmission AOV output. A small upstream patch corrects the
  mirror branch ignoring independent transmission roughness at zero reflection
  roughness. Shader and supporting library checksums are recorded.
- `probe_material.py`: mesh material assignment, shader/property queries, RDLA
  output and LXO save/reopen are verified inside Modo. Running it with
  `run_script_probe.py probe_material.py --material-undo` also confirms Undo
  removes the new shader and restores the previous polygon material tags.
- `probe_dock.py`: a graphical Modo 16.1v9 test confirms the current viewport
  changes to `customview` and contains the embedded preview. A Qt image capture
  confirms Modo's native viewport border. This is not the F9 render buffer API.
- `validate_live_process.py --surface`: a textured, instanced Moonshine scene
  passes real Qt render cancellation, replacement, image delivery and cleanup.
- The texture sampler fills a missing alpha channel with one, so RGB-only images
  remain opaque when composited. The named-UV/color-cache regression covers this.

Remaining limits include general BSDF layering, exact Modo procedural parity,
instance material overrides and the full Moonshine shader/attribute catalog.

## Native effect names and CPU scalar maps

- `probe_texture_effects.py` uses Modo's actual Shader Tree identifiers, including
  `diffColor`, rather than material-channel names. It checks supported aliases,
  raw scalar map conversion, below-material warnings and the standard-backend
  Specular Amount rejection. `probe_texture_repair.py` tests the no-restart repair.
- `validate_amount_maps.py` renders Diffuse Amount, Luminous Amount and Dissolve
  on both material paths, plus MoonShine Specular Amount. Black/white image regions
  must alter light, emission or alpha as appropriate. Each case compares scalar
  and AVX output. A separate constant-reference render verifies that color and
  amount stacks, including layer opacity, multiply once even with base amount zero.
- The user's captured geometry and original packaging image reproduced the
  texture issue locally; correcting the binding produced a textured sphere.
  The user also confirmed the repair in the running Modo preview. Private scene
  snapshots and rendered packaging images remain excluded from Git.

## CPU environment translation

- `probe_environments.py` verifies native Modo environment types, color/intensity,
  visibility channels, image connections, locator rotation, unsupported modes,
  radiance zero and scene-stored enable/multiplier settings in Modo 16.1v9.
- `validate_environments.py` renders color and doubled intensity, camera-hidden
  illumination, disabled diffuse/reflection/refraction visibility, three gradient
  types, HDR values above one, locator rotation and scalar/AVX agreement.
- `probe_environment_panel.py` passes inside a separate graphical Modo 16.1v9:
  the native docked panel can disable scene environments, multiply their intensity
  and store/reload both controls through scene settings.
- Gradient shape and absolute Modo-to-MoonRay HDRI azimuth have not been calibrated
  against Modo reference renders. No claim of exact environment parity is made.
