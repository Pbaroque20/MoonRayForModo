# XPU2 feature tests against MoonRay

The scripts that check XPU2's features against MoonRay, scene by scene (kept from the 2026-10-24 feature round).

- `make_*_scenes.py <folder> [...]`: writes a feature's test scenes (`.rdla` with an `OUTPUT` placeholder).
- `feature_compare.py <folder> <moonray_xpu2.exe> <cases...> [--moonray-mode scalar] [--floor xpu2|frame]`: renders each
  case with XPU2 (the session harness, `XPU2_SESSION_MODE` 0 for the CPU) and MoonRay, and prints the 8x8 block error
  and mean ratio against MoonRay beside the noise floor (by default XPU2 frame 1 against frame 0, one XPU2 render; `--floor frame`: a second MoonRay frame,
  for AOV comparisons).
- `runq.py`: a render queue shared by every running script (`RUNQ_SLOTS`, two by default) and a cache of MoonRay
  references keyed by scene, frame, mode and MoonRay build (`refcache/`); `seed_refcache.py` fills it from renders
  already on disk.
- `xpu2_only.py`: rerenders XPU2 alone against a case's existing MoonRay scene.
- `aov_compare.py`, `crypto_compare.py`, `region_grid.py`, `block_cmp.py`, `pixels.py`: every output channel group, the
  Cryptomatte layers, per-region mean differences, block statistics and single pixels.
- `cellular_check.py`: cellular and tree adaptive sampling and uniform sampling against a converged MoonRay image.
- `split_samplemap.py`: the one-time split of `shade::sampleMap` into a function per map type (GPU compile time).

MoonRay's vector mode crashes on emissive volumes, VDB emission and glitter on Windows: those references use
`--moonray-mode scalar`. Scenes, renders and the reference cache are not kept here.
