# XPU2 in MoonRay for Modo: where it stands

Private. A reference for picking up XPU2's use as the preview renderer in Modo, written 2026-10-24.
Everything here lives on the local branch `xpu2-async` and in `MoonRayForModo-xpu2/test-results` (git-ignored).

**Goal:** XPU2 renders Modo previews in MoonRay XPU's place, faster, with a final image that converges to
MoonRay's. Anything it can't render yet goes to MoonRay XPU automatically (the fallback).

Effort: S = hours, M = about a day, L = several days.
Shaders = changes XPU2's GPU programs, so Compile XPU2 Shaders (about an hour) must run again.

## What blocks real Modo scenes today

From the dragon scene (2026-10-24), XPU2 refused it before drawing anything; the preview you saw was MoonRay's.

| # | Area | Status | What remains | Effort | Shaders |
|---|------|--------|--------------|--------|---------|
| 1 | HDRI environment (EnvLight `texture`) | Not ported: XPU2's environment is a plain colour | Port MoonRay's image distribution: build the tables from the HDRI (colour correction, rotation, coverage, repeats, mirror), sample and evaluate as XPU's ISPC does (EnvLight.ispc, Distribution.ispc), mip level from the ray footprint, nearest and bilinear filters, visible in camera. About 2,400 lines of MoonRay C++ and ISPC to follow | L | Yes |
| 2 | Preview buffers | The kit asks for 26 (beauty, alpha, albedo, normals, depth, position, UV, motion, light-path AOVs, Cryptomatte and more); XPU2 makes beauty and alpha | Done in the private kit, not installed: XPU2 previews ask for beauty and alpha only. To do: the buffers themselves (row 3, then the rest) | S done | No |
| 3 | Denoising in previews | Off for XPU2 previews (MoonRay's denoiser needs albedo and normal guides) | Albedo (material AOV) and shading normal at the first hit, as extra film channels | M | Yes |
| 4 | Texture-bound and partial presence (cutouts) | Only presence 0 or 1, never a map | MoonRay's presence continuation (surface weighted by presence, ray goes on with the rest), shadow rays as MoonRay treats them (presence shadows off by default) | M | Yes |
| 5 | Textured MoonRay materials as Modo assigns them | Untested: the dragon's frame used Modo's default material, and the textured material wasn't assigned | Test an assigned material with ModoTextureMap, coat normal, transmission maps, DwaLayer SSS mix; fix what it refuses | S-M | Maybe |

## Done (session runtime 5, local commits up to 98ebb05)

| # | Area | Notes |
|---|------|-------|
| 6 | Kit protocol | Scene and command memory, deltas, cancel, drain, hold, progressive pictures, EXR outputs |
| 7 | Fallback to MoonRay XPU | XPU2 says why (status bar, Render Log), MoonRay takes the same scene; also when XPU2 crashes |
| 8 | Shader cache | Compile XPU2 Shaders in the background; a mark per program and driver; a stale cache falls back within a minute |
| 9 | Quads and n-gons | MoonRay's QuadMesh/TriMesh split and normals; matches MoonRay (block error 0.0007, noise 0.0003) |
| 10 | Mesh parts (`part_list`) | One piece per assignment, unassigned faces culled, whole-mesh normals |
| 11 | Only assigned materials | Unused materials no longer cause a fallback |
| 12 | Settings the kit always writes | Tile orders, motion and lens settings while those are off, deep settings, light labels |
| 13 | Budgets | 8 megapixels, 16 M triangles, textures up to 1 GB (.tx, which the kit makes) |
| 14 | Outlines | Buckets = the work grid's cells in use; worker tiles = each CPU thread's 8-pixel tile and the GPU's queued cells |

## Not ported (each falls back to MoonRay XPU)

| # | Area | Effort | Shaders |
|---|------|--------|---------|
| 15 | Motion blur | L | Yes |
| 16 | Depth of field, bokeh | M | Yes |
| 17 | Subdivision surfaces (`is_subd`) | L (OpenSubdiv tessellation as MoonRay does it) | No |
| 18 | Displacement on meshes with quads, n-gons or parts | M | No |
| 19 | Light filters, IES profiles (the interior scene has IES) | M-L | Yes |
| 20 | VDB volumes, OpenVdbMap, cutout volumes | L | Yes |
| 21 | Light-path AOVs (LPE), Cryptomatte, other AOVs | L | Yes |
| 22 | Camera film offsets, other camera types | S-M | Yes |

## Decided, not started

| # | Area | Notes |
|---|------|-------|
| 23 | Cellular-generation adaptive sampling, as the default | Each adaptive pass a generation, 8x8 tiles as cells alive while unconverged, neighbour rule with hysteresis; MoonRay's error trees stay as an option. Must converge to MoonRay's image: check against a 1024-sample MoonRay reference, and noise at equal time against the trees mode. Start on the host-pass path (no shader change) |

## Performance to look at

| # | Area | Notes |
|---|------|-------|
| 24 | Edits on big scenes | Each change copies the whole scene (CanonicalSession writes it as RDLB) and rebuilds the GPU scene: fine for the dragon (0.1 s), to measure on heavy scenes |
| 25 | CPU-only XPU2 | Slower than MoonRay's vector mode (203 s against 161 s on the polygon scene); XPU2 is meant for CPU and GPU together |
| 26 | Adaptive with the GPU | The CPU builds the error trees and takes no samples, so only GPU cells show as outlines |

## Measured so far

| Scene | XPU2 (CPU + GPU) | MoonRay XPU | Picture |
|-------|------------------|-------------|---------|
| Polygon test scene, 360x200, 1024 samples | 12.2 s | 122.8 s | Block error 0.0006 against MoonRay |
| Dragon from Modo, no HDRI, 1280x720, 16 samples | 9.1 s | 46.2 s | Mean ratio 1.002 |
| Material fixtures (first 10 of the final benchmark, 64 samples) | 86-92% less time | | All pass |

## Where things are

| What | Where |
|------|-------|
| Session program | `xpu2/interactive/xpu2_session.cc` (`--compile-shaders`, `--shaders-compiled`) |
| Runtime build | `build_session.py --build <async build>` writes `test-results/xpu2-session-N/runtime-xpu2`; latest is 5 (build 68's GPU programs) |
| Kit build | `test-results/xpu2-kit/build_xpu2_kit.py --session <...> --base <clean kit>`; the clean 0.4.3.1 kit is `xpu2-kit/backups/kit-20261024-011005` |
| Install / restore | `test-results/xpu2-kit/install_xpu2.py install` or `restore` (Modo closed) |
| Testing without Modo | `session_harness.py` (drives a session as the kit does), `xpu2-kit/check_xpu2_session_qt.py` (the kit's own session code, Modo's Python) |
| Final benchmark | Stopped at 10 of 59 cases; resume into a new folder with `--reuse material-benchmark-final material-benchmark-final2` |

**Installed in Modo now:** the first private kit (session runtime 4), which refuses scenes with parts or an HDRI.
The newer kit (runtime 5 and the beauty-and-alpha buffer list) is built in `xpu2-kit/MoonRayForModo` but not
installed. `install_xpu2.py restore` puts the stock 0.4.3.1 kit back.

**Suggested order:** 1 (HDRI) with 3 (guides) and 4 (presence) in one shader change, then 5, then 23 (cellular
sampling), then the rest as scenes need them.
