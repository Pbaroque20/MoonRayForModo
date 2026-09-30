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
  and swaps those rendered regions. Missing UVs and unsupported opacity blending
  are checked explicitly. Scripts: `probe_image_textures.py`, `validate_textures.py`.
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
