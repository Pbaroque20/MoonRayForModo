# Local validation — 2026-09-29

Test machine: Windows, Intel Core i7-4930K (AVX1, no AVX2), Modo 16.1v9.

- Native renderer: seven component tests pass, including AVX/ISPC mask ABI,
  64-bit codecs, Windows platform services, scene parsing and Embree intersection.
- Real scalar and AVX vectorized image renders succeed and exit normally.
  Invalid output paths fail promptly without hanging during DLL shutdown.
- Qt renderer: real cancellation, replacement image delivery and cleanup pass.
- Installed graphical Modo: a visible preview renders; moving a test mesh triggers
  live polling and a changed image without manually pressing Preview.
- Shadow investigation: the reported coarse sphere reproduces the stepped
  light/shadow boundary. Shadow-terminator compensation alone does not remove it.
  Catmull-Clark subdivision at resolution 8 removes the large polygon-shaped steps.
- Updated exporter: both Modo SUBD and Pixar PSUB faces are recognized inside
  Modo 16.1v9. Preview subdivision controls capture the expected mesh settings.
- All 17 plugin tests pass inside an isolated Modo 16.1v9 process, which exits 0.

Detailed machine-local reports and rendered comparisons are under `test-results/`
and build logs under `build/`; both are excluded from Git. These checks do not
establish full production scene compatibility or upstream regression coverage.

The source repository excludes compiled runtimes, downloaded dependencies,
upstream checkouts, toolchains, user scenes and Modo profiles. The native port's
patches, pinned source revisions, build configuration and scripts are included.
