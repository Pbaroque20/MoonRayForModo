# XPU2 engineer manual

How XPU2 works, part by part, with the files behind each part. Written 2026-10-25 against commit 242eb5c on
`xpu2-async`. The design notes it points to go deeper. Where this manual and the code disagree, the code wins: fix
the manual.

All paths are relative to `xpu2/interactive/` unless they start with `xpu2/` or another top-level folder.

![XPU2 architecture](xpu2_architecture.svg)

The diagram shows the code as of session 99. It doesn't yet show realtime previews (section 5.11), the Modo scenes
round (`INDEXER.md` sections 14 and 15) or the fine-detail texture cache's measured budget (section 5.9), which
replaced the 512 MB cache drawn in the GPU lane.

## Contents

1. [What XPU2 is](#1-what-xpu2-is)
2. [The rules everything rests on](#2-the-rules-everything-rests-on)
3. [Processes: Modo, the kit, the session, the fallback](#3-processes-modo-the-kit-the-session-the-fallback)
4. [A frame from start to finish](#4-a-frame-from-start-to-finish)
5. [The parts](#5-the-parts)
6. [File map](#6-file-map)
7. [How correctness is kept](#7-how-correctness-is-kept)
8. [Switches for testing and diagnosis](#8-switches-for-testing-and-diagnosis)
9. [Building and running](#9-building-and-running)
10. [Testing against MoonRay](#10-testing-against-moonray)
11. [Porting a MoonRay feature](#11-porting-a-moonray-feature)
12. [Glossary](#12-glossary)
13. [Not done yet](#13-not-done-yet)
14. [Further reading](#14-further-reading)

## 1. What XPU2 is

XPU2 is a preview renderer for MoonRay for Modo. It takes the same RDL scene the kit gives MoonRay and renders it
with the CPU and the GPU on the same image at the same time. The goal is MoonRay's image, sooner: every estimator,
light, BSDF lobe, material and map is MoonRay's, ported to code that runs on both devices, and every port is checked
against MoonRay renders.

It follows the Interactive xPU Renderer Spec (21 October 2026). Spec requirement IDs (ARC-01, CA-08, ACC-07, ...)
appear in code comments. Section 12 explains the prefixes.

XPU2 is a private test build. It renders previews only: final renders, MoonRay LS and MoonLightIPR stay MoonRay's.

## 2. The rules everything rests on

These hold everywhere. A change that breaks one is a bug, even when the picture looks right.

1. **A sample is defined by its identity, not by who renders it.** A sample is (pixel, sample index, frame seed).
   Its random numbers come from that identity alone (`sample_stream.h`), so either device computes the same sample,
   and a sample can move between devices at any point before it starts.
2. **One integrator for both devices.** The path tracer and shading library are written once, as `X2_HD` code
   (host and device), and compiled for the CPU lane and for the GPU program. There is no "GPU version" of a shader to
   keep in step.
3. **Neither device waits for the other.** The host never blocks on the GPU (it polls events), and the GPU always has
   a launch queued (spec ARC-01).
4. **A chunk of work is claimed exactly once**, by one atomic on a cursor in host memory (CA-06). Nothing is shared
   across PCIe.
5. **A started sample is never dropped, and nothing is counted twice** (ACC-03). When a frame ends, the two films are
   merged and every pixel's sample count is audited (ACC-07).
6. **No path state crosses devices.** When the GPU can't finish a sample (a feature its programs lack), the CPU renders
   that sample again from its identity. The GPU's partial work is thrown away.
7. **Never blend renderers.** A scene is either XPU2's or MoonRay XPU's, whole. XPU2 never patches pixels into a
   MoonRay image or the other way round.

## 3. Processes: Modo, the kit, the session, the fallback

```
Modo ── MoonRay for Modo kit (private build) ──► moonray_xpu2.exe  (XPU2 preview session)
                 ▲            │                        │
                 │            │  "@@MODO_XPU2 FALLBACK <reason>"
                 │            └──────────────► moonray.exe (MoonRay XPU takes the same scene)
                 └── pictures through shared memory, @@MODO_* protocol lines on stdout
```

- **The private kit** (`xpu2/tools/kit/build_xpu2_kit.py`) is the standard kit with XPU2 added. A preference picks
  the GPU renderer (MoonRay XPU or XPU2). When XPU2 is chosen and the render's execution mode is XPU or Auto, the
  preview session starts `moonray_xpu2.exe` in MoonRay's place.
- **The session program** (`xpu2_session.cc`, built as `moonray_xpu2.exe`) speaks the kit's persistent preview
  protocol v1, the same one MoonRay's session speaks (`native-port/persistent_session.inc`). It reads the scene and
  later deltas, renders frames, writes pictures to shared memory, and answers drain, hold and cancel.
- **The fallback.** If XPU2 doesn't render something in the scene, its GPU programs aren't compiled, or the GPU fails,
  the session prints `@@MODO_XPU2 FALLBACK <reason>` and exits. The kit then starts MoonRay XPU on the same scene and
  the Render Log shows the reason. It does the same if XPU2 crashes. When the scene changes so XPU2 can render it
  again, XPU2 takes it back.
- **Without `MOONRAY_MODO_SESSION`**, `moonray_xpu2.exe` passes its arguments to the kit's own `moonray.exe`
  (`MOONRAY_XPU2_MOONRAY` names it), so a final render started through it is MoonRay's.

## 4. A frame from start to finish

1. **The scene arrives.** The kit sends an RDL scene (mesh arrays as RDLB binary), then deltas for each edit.
2. **Indexing.** The canonical session (`canonical_session.h`) keeps every RDL object and attribute, updated
   incrementally. The classifier (`entity_classes.h`) gives each object a device class: `Fallback`, `Cpu` or `Both`,
   and the GPU feature families it needs. The router (`routing_index.h`) keeps one decision per object and redoes only
   what an edit touched.
3. **Scene mode.** Any `Fallback` object sends the scene to MoonRay (section 3). Some features keep the whole scene on
   the CPU lane: light filters, shadow linking, lobe light sets, lights in motion and emissive volumes.
4. **The plan.** `cpu::prepare` (`cpu_scene.h`) turns the scene into flat records both lanes read: meshes
   (tessellated and displaced, reused by signature when unchanged), materials and their map programs, lights, the
   light tree, light filters, volumes and NanoVDB grids, textures as host mip pyramids, the camera, and the render
   outputs. It is also the last check of every attribute: an object classified `Both` can still be refused here.
5. **The lanes prepare.** The CPU lane builds its Embree scene, and the GPU lane builds its OptiX acceleration
   structures and uploads the scene. A camera-only edit keeps all of this and only updates the camera (section 5.11).
6. **Cells are seeded.** A first-hit probe (four camera rays per tile, on the CPU) finds what each cell of the image
   sees. Each cell starts on the device suited to it (`device_suit.h`).
7. **The frame runs.** Both lanes claim chunks (an 8×8 tile and a range of sample indices) from the work grid
   (`async_grid.h`). The CPU lane's workers claim their own. The feeder thread claims for the GPU and keeps two
   launches queued (`async_render.h`). Every sample runs the shared integrator (`async_integrator.h`) start to
   finish and adds its result to its lane's film.
8. **Samples hand off.** A GPU sample that meets a feature the GPU lacks goes to the CPU's retry queue (deferred).
   A GPU sample whose fine texture tile isn't resident yet finishes from a coarser mip level and counts as
   provisional until it's rendered again in full (partial shading, section 5.9).
9. **Sampling generations decide when to stop.** After each pass, tiles whose error is still above the target sample
   again (section 5.8). The frame ends when the budget or the target is reached, or on Stop.
10. **Merge and output.** The films merge and sample counts are audited. AOVs, Cryptomatte and display filters are
    written as MoonRay writes them (`aov_*.h`). Pictures go to the kit through shared memory, with the kit's denoiser
    guides (albedo, normal) when asked.

## 5. The parts

### 5.1 The session program

`xpu2_session.cc` (`moonray_xpu2.exe`). It is the only part that knows about Modo's protocol. It holds:

- the protocol loop (`session()`): the scene and command mailboxes, generation IDs, `drain.txt` and `hold.txt`
  (control files that name the render they apply to), and `@@MODO_SESSION` events;
- the shader cache check: `--compile-shaders` compiles the GPU programs into OptiX's disk cache (about an hour the
  first time) and leaves a mark for this driver and these programs. `--shaders-compiled` exits 0 when the mark is
  there and 3 when it isn't. If the cache is gone (a driver update, the cache's size limit), the session hands the
  scene to MoonRay after a minute rather than compile for an hour;
- outlines for the kit: `@@MODO_TILES` (cells being rendered), `@@MODO_WORKERS` (each CPU worker's tile) and
  `@@MODO_GPU_WORKERS` (cells the GPU's queued launches hold, drawn in their own colour);
- checkpoints for Safe Denoising (class `Checkpoints`): the frame so far, saved every `checkpoint_interval` minutes,
  with MoonRay's "Wrote:" lines. Continue starts the render again; resuming from a save isn't done yet;
- the realtime denoiser (class `RealtimeDenoiser`, section 5.11);
- the memory ceiling and the geometry budget (1 GiB of prepared geometry unless `XPU2_SESSION_GEOMETRY_MB` is set);
- the frame report in the log: when the grid ran out of chunks, the GPU's launches and rate, parked samples, texture
  cache loads and evictions, and the GPU profile when `XPU2_PROFILE` is set.

`xpu2_scene.cc` and `xpu2_cpu.cc` are three-line units that split the build into translation units:
`build_session.py` compiles the scene admission (`cpu::prepare`) and the CPU integrator separately, in parallel.

### 5.2 The scene indexer and routing

Design: `INDEXER.md` sections 1 to 4.

| File | Role |
|---|---|
| `xpu2/indexed_scene.h`, `xpu2/rdl_scene_index.h`, `xpu2/rdl_replica.h` | The scene index: every RDL object and attribute, captured incrementally |
| `canonical_session.h` | The scene-service adapter. Renderers receive immutable RDLB files, never pointers into the mutable replica. Call only on its owning thread |
| `entity_classes.h` | The classifier: support (`Fallback`, `Cpu`, `Both`), GPU feature families (one bit each), relative cost per device |
| `routing_index.h` | One routing decision per entity, redone only for what an edit touched. Unknown means fallback |
| `device_suit.h` | Cells by suitability: the first-hit probe and each cell's probability that the GPU is its efficient owner |
| `snapshot_budget.h` | How many immutable index versions may be kept |

A material is classified by the families its BSDF tree and map graph use, so one glitter material among many DwaBase
ones doesn't decide the whole scene.

### 5.3 The plan builder

`cpu_scene.h` (`cpu::prepare`, about 3,600 lines) and the admission headers it includes. Preparation is not
qualification: it reads attributes with MoonRay's defaults and refuses what XPU2 doesn't render, with a reason.

| File | Role |
|---|---|
| `cpu_scene.h` | The plan: meshes, instances, parts, lights, the camera, render settings, sampling generations' settings (UserData `/modo/xpu2/generations`), limits. `X2_NEED` builds its message only on failure: building it every time cost seconds in loops over millions of indices |
| `dwa_admission.h` | DwaBase-family objects into `shade::DwaRecord`s, with `DwaBase::update()`'s hints |
| `map_admission.h` | Material bindings into `MapBinding`s and each material's map program, in dependency order |
| `mesh_displacement.h` | MoonRay's PolyMesh tessellation and displacement for triangle meshes |
| `light_tree_build.h`, `light_image_build.h`, `light_mesh_build.h` | Light tree, light textures and mesh lights, built on the host |
| `aov_plan.h` | Render outputs as MoonRay's RenderOutputDriver sets them up: files, parts, channels, the AOV schema, material AOV expressions and LPE state machines |
| `xpu2_geom.cc`, `xpu2_geom.h` (`xpu2_geom.dll`) | MoonRay's own OpenSubdiv tessellation, displacement callbacks and OpenVDB reading, built separately with MoonRay's flags (`build_geom.py`) so XPU2's build never sees MoonRay's internal headers |

Unchanged meshes, tessellations, grids, images and light tables are reused across edits by signature.
`deepSignature` covers a displaced mesh's maps.

### 5.4 The work grid and scheduling

Design: `ASYNC.md` ("How a frame runs"), `INDEXER.md` section 7.

- **Grid** (`async_grid.h`). The image is cut into 64-pixel cells. Each cell queues its unstarted work as 16-byte
  chunks (one 8×8 tile and a sample range), ordered by sample range so a cell converges evenly. Claims are atomics on
  host cursors.
- **Ownership.** Cells start by suitability (`device_suit.h`), otherwise in a CPU/GPU checkerboard. They flip towards
  the device that rendered most of them: at most 8 flips a frame, a 16-frame cooldown, and a 64-frame freeze after
  thrashing. Deferred samples count as the CPU's.
- **Progressive order.** A uniform frame's sample ranges grow 1, 1, 2, then the chunk size. No device gets a chunk past
  the least-sampled range of the cells it works, unless it holds a right of passage, so the whole picture fills first.
- **Important parts first.** The pictures so far score each cell (MoonRay's tile score). Cells above the mean stay with
  their owner and may run a range ahead. The rest are open to either device, most important first.
- **Rights of passage.** A device may enter a cell the other has reserved only when that can't hold up the frame. The
  CPU may enter when its chunk would end before the GPU gets there, or when the GPU hasn't claimed lately. The GPU may
  enter when the CPU's backlog outlasts four of its launch windows, in a cell it wouldn't mostly defer.
- **Cellular workers on both devices.** 12 CPU threads by default (`RenderOptions::threads`) and 32 GPU workers (shares
  of each launch) each sit in a cell and move by the same rules: finish the cell, then their own reserved cells, then
  open cells, then by passage, neighbours first.
- **The feeder** (`async_render.h`). One thread, pinned to its own core, is the GPU's broker. It claims chunks for the
  GPU, keeps two launches queued, and sizes each from the GPU's measured rate: about 10 ms of work (`windowMs`), never
  below two samples per thread of the 65,536-thread launch. Near the end of a frame it splits what's left so both
  devices finish together (the lookahead).
- **Low latency** (`async::lowLatency`). When the kit lowers the process's priority, no XPU2 thread is raised above it
  and one CPU thread is left free for Modo.

### 5.5 The CPU lane

`async_cpu.h`. Persistent, pinned workers. Embree in robust mode traverses triangles, and user geometry handles curves
and points. The CPU lane:

- renders every feature XPU2 has, including those the GPU defers: points, geometry in motion, VDB volumes,
  heterogeneous and emissive volumes;
- takes the retry queue: deferred GPU samples, each rendered whole from its identity;
- re-renders provisional samples in full (every texture level is in RAM, so the CPU never misses);
- keeps its own film, merged with the GPU's at the end of the frame.

`cpu_pool.h`, `cpu_jobs.h`, `cpu_lane.h` and `cpu_service.h` are prototype-era pieces (section 6).

### 5.6 The GPU lane

Host side: `async_gpu.h` (about 2,200 lines). Device side: `async_gpu.cu` and the module files. Shared layout:
`async_gpu_abi.h` and `async_gpu_device.h`.

- **One CUDA stream** carries everything in order: chunk uploads into the mailbox ring, launches, readbacks and
  texture-cache updates. The host polls events.
- **Launches.** Fixed grids of 65,536 threads (`launchThreads`). Each thread claims one sample at a time with an
  atomic: first parked samples, then its range of chunk items. Neighbouring claims are neighbouring pixels of the same
  sample, so warps trace coherent rays. The device film accumulates in double precision.
- **Acceleration structures.** One GAS per mesh, kept while the mesh is unchanged, under an IAS. Curves use MoonRay
  XPU's own intersection programs as custom primitives.
- **Stand-ins.** Entities classified `Cpu` are in the GPU scene as bounding stand-ins: a moving mesh's motion bounds,
  a VDB's box, points' bounds. A sample that meets one defers to the CPU lane through the deferred-samples ring.
- **The program in nine modules,** compiled by OptiX in parallel. A module's call graph compiles as a whole, so the
  split keeps every module small:

  | Module source | Holds |
  |---|---|
  | `async_gpu.cu` | Ray generation, misses, hits: the path loop, light sampling, the traces |
  | `async_material.cu` | A hit's BSDF, a material's presence |
  | `async_maps.cu` | The map interpreter |
  | `async_lights.cu` | Light shapes: sampled, intersected, evaluated |
  | `async_lobes.cu` | Lobes: evaluated, sampled, their albedo |
  | `async_volumes.cu` | Volume radiance, subsurface, shadow transmittance (continuation callables, because they trace) |
  | `async_dwa.cu` | DwaBase resolve: a tree's layers blended |
  | `async_dwalobes.cu` | A resolved DwaBase material's lobes, glitter |
  | `async_extras.cu` | Extras: the camera, AOVs |

  Direct callables can't trace rays in OptiX 7.6, so anything that traces is a continuation callable or stays in
  ray generation. Callable modules are compiled relocatable (`-rdc`), or NVRTC drops their entry points. Big helpers
  are kept out of line (`X2_CALL`, beside `X2_HD` in `sample_stream.h`). No OptiX call may appear inside the map
  callable: it took one module's compile from seconds to 40 minutes.
- **`async_adaptive.cu`** holds the CUDA kernels of the adaptive pass chain (section 5.8). It is a CUDA program, not an
  OptiX module.
- **Profile.** `XPU2_PROFILE` makes the GPU time each stage (rays, shadow rays, material callables, presence, volume
  crossings) and count rays per sample. The session prints the shares.

### 5.7 The shared integrator and the shading library

Design: `PATH_TRACER.md`.

`async_integrator.h` (about 2,800 lines) is one complete sample, start to finish: MoonRay's estimator with light and
BSDF samples combined by MIS, per-lobe depth limits, Russian roulette, sample clamping, presence continuation,
volumes, subsurface, Cryptomatte events and AOVs. It is templated on a backend (`integrate<Backend>`), so the CPU lane
and the GPU program run the same code with their own traversal and texture access.

**Bounce-ray reuse.** A BSDF sample that reaches a light and continues as a bounce needs no separate shadow ray: the
bounce's nearest hit settles it. This halved the shadow rays on the Modo test scene. It is off where the two could
differ: presence shadows, shadow linking, volumes, minimum shadow distance and similar cases (`Config::shadowReuse`).

| Area | Files |
|---|---|
| Cameras (perspective, orthographic, depth of field and bokeh, spherical, fisheye, DomeMaster3D, bake) | `camera_core.h` |
| Lights, light tree, light filters, light textures | `light_core.h`, `light_tree.h`, `light_filter_core.h`, `light_image.h` |
| Shading state at a hit, primitive attributes | `shade_state.h`, `surface_core.h`, `triangle_hit.h`, `resume_core.h` |
| Materials: DwaBase family, combinators, UsdPreviewSurface, switch materials | `shade_dwabase.h`, `shade_dwalayer.h`, `shade_material.h`, `shade_builder.h` |
| Maps: bindings, map programs, map nodes | `shade_maps.h`, `shade_mapnodes.h`, `shade_mapnodes_more.h`, `shade_noise.h`, `shade_color.h`, `shade_colorcorrect.h` |
| BSDF lobes and Fresnel | `shade_lobes.h`, `shade_lobes_eval.h`, `shade_fresnel.h` |
| Subsurface | `shade_bssrdf.h` |
| Hair, glitter, flakes | `shade_hair.h`, `shade_glitter.h`, `shade_glitter_tables.h`, `shade_flakes.h` |
| Volumes and VDB, emissive volumes | `volume_core.h`, `volume_grid.h`, `volume_emission.h` |
| Curves and points | `curve_core.h`, `curve_embree.h` (vendored by `vendor_curves.py`), `points_core.h` |
| Math helpers, shared tables | `shade_math.h`, `shade_tables.h` (made by `make_shade_tables.py`) |

XPU2 shades in world space; MoonRay shades in render space. Where MoonRay reads a value as a render-space quantity,
XPU2 converts it (`PATH_TRACER.md`, "Render space"). Missing that conversion shows up as shifted highlights.

### 5.8 Sampling

- **Random numbers** (`sample_stream.h`). The camera, first-hit BSDF, light and subsurface dimensions are stratified
  across a pixel's samples (Sobol, digitally shifted). Everything else comes from a per-bounce Philox4x32-10 stream in
  a fixed order. All of it derives from the sample's identity. Branch IDs are deterministic tree addresses, never
  queue order.
- **Sampling generations** (`async_adaptive.h`, class `Cellular`). Every frame runs by generations. Each generation is
  a pass; tiles whose error is above the target sample the next pass. The scene's sampling mode only decides when to
  stop:
  - uniform: every pixel is seeded with an eighth of its samples (at least 16). The rest go where the error is, within
    the time uniform sampling would have taken. At most twice the uniform total, and 16 times the samples per pixel;
  - adaptive: until the target error, between the minimum and maximum samples.

  With a GPU, the CPU lane takes chunks too, and the two lanes' errors are pooled by their counts
  (`Adaptive::merged`). The kit's render settings (XPU2 Sampling Generations, Samples, Spend, Noise Target, First
  Generation, Most Samples, CPU Workers) reach the scene as UserData `/modo/xpu2/generations`.
- **MoonRay's error trees** (`XPU2_SESSION_ADAPTIVE=trees`) are still available: MoonRay's own adaptive sampler, the
  same error measure, regions, trees and pass schedule. The host and the GPU build identical trees from
  `async_adaptive_core.h`, which writes out every multiply-add a compiler could fuse (`mulRn`, `addRn`).
- **The pass chain** (`async_adaptive.cu`, `GpuLane::launchChain`, `XPU2_SESSION_CHAIN=1`). A whole adaptive frame
  queued on the GPU at once: per pass, four CUDA kernels (errors, trees, masks, compaction) and an OptiX render. Off
  by default in sessions.

### 5.9 Textures

- Host RAM holds every mip level of every texture and is the system of record (`host_texture.h`). The CPU reads it
  directly.
- VRAM holds every texture's levels 1 and up for the whole session, plus a cache of level-0 (fine-detail) tiles,
  loaded on demand and evicted least recently used.
- The cache's budget (`GpuLane::fineBudget`) is measured at each preparation: what the scene's level-0 tiles need, up
  to the card's free memory minus a fifth of the card (at least 1.5 GB left for the frame and Modo's viewport), and
  never below 256 MB. `XPU2_SESSION_FINE_BUDGET_MB` fixes it.
- Filtering is OpenImageIO's algorithm, shared by both devices (`texture_core.h`). A miss names the tile it needs in a
  scene-wide tile space.
- **Partial shading** (on by default). A GPU sample whose level-0 tile isn't resident finishes from the parent texel a
  level up and is provisional: shown in the pictures, kept out of the film. The CPU, or the GPU once the tile lands,
  renders it again in full. A frame ends with no provisional samples left (audited). A drain (Stop) finishes the
  provisional samples first. With `XPU2_SESSION_PARTIAL=0`, such samples park in a bounded GPU queue until their tile
  lands instead.
- Pinned host memory for readbacks is capped at a quarter of the machine's memory, between 2 and 16 GB.

### 5.10 Film and outputs

| File | Role |
|---|---|
| `aov_core.h` | A sample's AOV values in one array laid out as MoonRay's AovSchema, merged by MoonRay's filters (average, sum, min, max, closest) |
| `aov_material.h` | Material AOVs from the lobes, Fresnels and subsurface, with PBR validity |
| `aov_state.h` | State-variable and primitive-attribute AOVs, depth, wireframe |
| `aov_crypto.h` | Cryptomatte as MoonRay's vector mode keeps it, with the kit's Modo categories |
| `aov_display.h` | Display filters: runs MoonRay's own display filter DSOs over XPU2's buffers |
| `aov_write.h` | The EXR files as MoonRay writes them: parts, channels, compression, metadata, windows |

The pictures fill pixels no sample has reached yet from their neighbours, for display only.

### 5.11 Realtime

Design: `INDEXER.md` section 13. With the kit's RT switch on, the preview follows the scene at the realtime size.

- A camera-only edit (`Scene::onlyCameraDirty`) keeps the plan, the CPU scene and the GPU scene.
  `cpu::updateCamera` and `GpuLane::updateCamera` take about 0.1 ms. Scenes whose geometry depends on the camera
  (adaptive subdivision, volumes, filters, a pixel sample map, motion) prepare again.
- A realtime frame is the GPU's alone. Its first two passes are sparse (a quarter of the pixels, then the rest), with
  launches sized to about 15 ms and a picture every 33 ms.
- With Denoised Beauty chosen, `RealtimeDenoiser` runs OptiX's HDR denoiser on its own high-priority stream, with the
  kit's guides. The albedo guide is cleaned first, and normals are in camera space. Pictures with unsampled pixels are
  denoised at half size.

## 6. File map

Everything in `xpu2/interactive/`, grouped by part. Line counts are approximate.

**The session and its builds**

| File | What it is |
|---|---|
| `xpu2_session.cc` (1.3k) | `moonray_xpu2.exe`: the protocol, fallback, outlines, checkpoints, realtime denoiser |
| `xpu2_scene.cc`, `xpu2_cpu.cc` | Translation units of the session build |
| `build_session.py` | Builds the session runtime: `moonray_xpu2.exe`, the GPU programs, the pinned runtime's libraries |
| `build_async.py` | Builds the renderer's test worker (`async_probe.exe`) and its OptiX program |
| `build_geom.py` | Builds `xpu2_geom.dll` with MoonRay's flags |
| `native_build.py`, `gpu_build.py` | The shared C++ and NVRTC build helpers |
| `reference_runtime.py`, `reference-lock.json` | The pinned MoonRay reference runtime and its hash lock (1,135 files) |
| `session_harness.py` | Drives a session as the kit does, without Modo |

**The renderer**

| File | What it is |
|---|---|
| `async_render.h` (1.3k) | Coordinator, feeder and broker, `RenderOptions`, the frame's end, merge and audit |
| `async_grid.h` (0.5k) | Work grid, chunks, cellular rules, ownership flips |
| `device_suit.h` | Cells by suitability |
| `async_cpu.h` (1.5k) | CPU lane |
| `async_gpu.h` (2.2k) | GPU lane, host side |
| `async_gpu.cu` and the `async_*.cu` modules | GPU program |
| `async_gpu_abi.h`, `async_gpu_device.h` | Host/device shared layout, launch parameters, device texture access |
| `async_integrator.h` (2.8k) | One sample, both devices |
| `async_adaptive.h`, `async_adaptive_core.h`, `async_adaptive.cu` | Sampling generations, error trees, the GPU pass chain |
| `async_probe.cc` | The benchmark worker the `run_async_*` scripts drive |

**The scene**

| File | What it is |
|---|---|
| `canonical_session.h`, `routing_index.h`, `entity_classes.h` | Indexer, router, classifier |
| `cpu_scene.h` (3.6k) | Plan builder |
| `dwa_admission.h`, `map_admission.h`, `mesh_displacement.h` | Material, map and displacement admission |
| `light_*_build.h` | Light tables built on the host |
| `xpu2_geom.cc`, `xpu2_geom.h` | MoonRay's tessellation and OpenVDB, as a DLL |

**Shared shading:** see the table in section 5.7. **Outputs:** see section 5.10.

**Prototype-era files.** The synchronous parity pipeline and the 22 October prototype: `deadline_pipeline.h`,
`mixed_*.h`, `cpu_lane.h`, `gpu_lane.h`, `cpu_pool.h`, `cpu_jobs.h`, `cpu_service.h`, `gpu_jobs.h`, `path_stage.h`,
`progressive.h`, `sample_tree.h`, `prototype_*.py`, and most `*_probe.cc` files with their `run_*.py` drivers. The
parity pipeline stays as the exact-arithmetic reference (fixed ownership, byte-repeatable images). It is not the
preview path.

**Elsewhere in the repository**

| Path | What it is |
|---|---|
| `native-port/persistent_session.inc`, `native-port/modo_*.h` | The kit's preview protocol, shared with MoonRay's session |
| `xpu2/tools/kit/` | `build_xpu2_kit.py`, `install_xpu2.py`, `check_xpu2_session_qt.py` |
| `xpu2/tools/modo-cl/` | Headless Modo export (`run_cl.py`, `export_probe.py`), comparison (`compare.py`), crash debugging (`debug_modo.py`) |
| `xpu2/*.md`, `xpu2/*.cc` (top level) | The first attempt (October 16): historical |

## 7. How correctness is kept

- **Same estimator, same random numbers.** Shared `X2_HD` code and identity-derived random numbers mean a sample is
  the same sample on either device. Embree and OptiX may still find slightly different hits; the differences are
  measured statistically (spec CPU-12).
- **Fused arithmetic is written out** where both devices must agree exactly (the error trees): `mulRn`, `addRn`.
- **Audits.** Every pixel's sample count is checked when the films merge. No provisional sample is left at a frame's
  end.
- **MoonRay quirks are a choice, made per quirk.** Some vector-mode behaviours are reproduced and others are not (XPU2
  matches scalar mode there). `FEATURE_PROGRESS.md` lists each one.
- **Every port is checked against MoonRay**: block error and mean ratio against MoonRay's own seed-to-seed noise
  floor (section 10).
- **Test with the kit's Source Overrides.** Without the kit's environment, some scenes render differently in both
  renderers (for example `MOONRAY_MODO_OPAQUE_ALPHA`). `compare.py` takes `--env`.

## 8. Switches for testing and diagnosis

Environment variables read by the session or the renderer. Defaults are the shipping behaviour.

| Variable | Effect |
|---|---|
| `XPU2_SESSION_MODE` | `0` CPU only, `1` GPU only, `2` both (default) |
| `XPU2_SESSION_PARTIAL=0` | No partial shading: texture misses wait for their tile |
| `XPU2_SESSION_ADAPTIVE=trees` | MoonRay's error trees instead of sampling generations |
| `XPU2_SESSION_ADAPTIVE_CPU=0` | With generations, the GPU takes every chunk |
| `XPU2_SESSION_UNIFORM_BUDGET=0` | Exact uniform sampling (for comparisons with MoonRay's uniform renders) |
| `XPU2_SESSION_CHAIN=1` | The adaptive pass chain on the GPU |
| `XPU2_SESSION_SHADOW_REUSE=0` | No bounce-ray reuse |
| `XPU2_SESSION_PREVIEW_MS` | Interval between progressive pictures (default 100) |
| `XPU2_SESSION_LOW_LATENCY` | `0` or `1`: overrides the kit's low-latency setting |
| `XPU2_SESSION_FINE_BUDGET_MB` | Fixes the level-0 texture cache's budget |
| `XPU2_SESSION_GEOMETRY_MB` | Prepared-geometry budget (default 1 GiB) |
| `XPU2_SESSION_RT_DENOISE=0`, `_RT_GUIDES`, `_RT_SHOW`, `_RT_DEBUG`, `_RT_PRIORITY=0` | Realtime denoiser diagnostics (`INDEXER.md` section 13) |
| `XPU2_SESSION_DEBUG_FAILURES` | Names the CPU lane's first failed shadings and texture lookups |
| `XPU2_PROFILE` | GPU profile by stage, printed per frame |
| `XPU2_OPTIX_LEVEL` | `0` to `3`: lower OptiX optimization for quick GPU test builds (cached as a separate program) |
| `XPU2_OPTIX_EXCEPTIONS` | OptiX exception checks in the GPU program |
| `XPU2_ASYNC_HOST_PASSES=1`, `XPU2_ASYNC_TREE_THREADS`, `XPU2_ASYNC_NO_RESERVE` | Benchmark worker (`async_probe.exe`) options |

The `XPU2_*_MODULE` and `XPU2_*_UNIT` macros are build-time defines that select which module or unit a source file
compiles as. They are not runtime switches.

## 9. Building and running

Prerequisites, and the pinned reference runtime, are in `BUILDING.md`: the Windows MoonRay development tree
(`toolchain/msys64` g++, `build/native-avx`), Embree 4.4.1, OpenImageIO 3.1.17, OptiX 7.6 headers, CUDA 12.8 runtime
and NVRTC, and an NVIDIA GPU. Every output folder must be new.

```powershell
# 1. The renderer and its GPU program (also the benchmark worker)
python xpu2/interactive/build_async.py --source $toolchainRoot --runtime $referenceRoot --output test-results/async-build-N

# 2. The session runtime the kit runs: moonray_xpu2.exe, xpu2_geom.dll (cached by its sources), the GPU programs
#    of build N, and the pinned runtime's libraries
python xpu2/interactive/build_session.py --source $toolchainRoot --runtime $referenceRoot --build test-results/async-build-N --output test-results/xpu2-session-N

# 3. Compile the GPU programs into OptiX's cache (about an hour the first time; cached after)
test-results/xpu2-session-N/runtime-xpu2/moonray_xpu2.exe --compile-shaders

# 4. The private kit, from the clean standard kit and the session
python xpu2/tools/kit/build_xpu2_kit.py --session test-results/xpu2-session-N --base <clean kit>

# 5. Install it (Modo closed); "restore" puts the standard kit back
python xpu2/tools/kit/install_xpu2.py install
```

Run each script with `--help` for its full arguments. Notes:

- `build_session.py` refuses an async build whose GPU program sources have changed since. Build again (step 1), or
  pass `--cpu-test` for CPU-only tests (`XPU2_SESSION_MODE=0`), which never load the GPU programs.
- Any change to code the GPU program includes means compiling the shaders again (step 3). Use `XPU2_OPTIX_LEVEL=0`
  for quick correctness builds.
- The kit tools run from `MoonRayForModo-xpu2/test-results/xpu2-kit/` on the development machine (git-ignored). The
  copies in `xpu2/tools/` are kept for safekeeping.
- Close Modo before installing, and check `tasklist` shows no `modo.exe`.
- Never attach gdb to Modo: its JIT breakpoint on `nvgpucomp64` kills Modo. Use `xpu2/tools/modo-cl/debug_modo.py`.

## 10. Testing against MoonRay

| Check | How |
|---|---|
| Unit tests | `python -m unittest discover -s xpu2/interactive -p "test_*.py"` |
| Scheduler invariants | `async_grid_test.cc`: every chunk claimed once under 12 workers and the broker, every pixel gets exactly its samples, cellular rules, flip limits |
| Feature against MoonRay | `feature_tests/make_*_scenes.py` writes a feature's scenes; `feature_tests/feature_compare.py` renders XPU2 and MoonRay and prints 8×8 block error and mean ratio beside the noise floor |
| Outputs | `feature_tests/aov_compare.py`, `crypto_compare.py` |
| Sampling | `feature_tests/cellular_check.py`: generations, trees and uniform against a converged MoonRay image |
| A session as the kit drives it | `session_harness.py --exe moonray_xpu2.exe --scene ... --output ...` |
| A real Modo scene | `xpu2/tools/modo-cl/` exports headless; `compare.py <scene> <w> <h> --moonray --xpu2 <session>` |
| Speed | `run_async_benchmark.py`, `run_async_adaptive_benchmark.py`, `run_material_benchmark.py` |

MoonRay's vector mode crashes on Windows for emissive volumes, VDB emission and glitter. Compare those against
`--moonray-mode scalar`. Never render anything else while a benchmark is timing.

## 11. Porting a MoonRay feature

1. **Read MoonRay's code** for the feature, both the scalar C++ and the vector ISPC, since XPU follows the ISPC. Note
   the quirks.
2. **Port the device code** as `X2_HD` into the right shared header (section 5.7). Keep MoonRay's operation order.
   Credit the MoonRay source file in the header comment (Apache-2.0).
3. **Admit it on the host**: the plan builder reads its attributes with MoonRay's defaults (`cpu_scene.h` or an
   admission header) and refuses what's out of scope with a clear reason.
4. **Classify it** in `entity_classes.h`: `Both`, `Cpu` (with a GPU stand-in) or `Fallback`, and its GPU family.
5. **Place it in a GPU module.** Keep modules small, and nothing that traces in a direct callable.
6. **Write test scenes** (`feature_tests/make_<feature>_scenes.py`) and compare: on the CPU lane first
   (`XPU2_SESSION_MODE=0`, 256 samples a pixel), then on the GPU after a shader compile.
7. **Record it** in `FEATURE_PROGRESS.md` with the check's numbers, and update this manual if a part changed.

## 12. Glossary

| Term | Meaning |
|---|---|
| Lane | One device's renderer: the CPU lane or the GPU lane |
| Tile | 8×8 pixels |
| Cell | 64×64 pixels: the unit of ownership, scheduling and outlines |
| Chunk | 16 bytes of work: one tile and a range of sample indices |
| Feeder, broker | The host thread that claims chunks for the GPU and keeps its launches queued |
| Mailbox | The device-memory ring the feeder passes chunks through |
| Frontier | The least-sampled range a device may hand out without a right of passage |
| Right of passage | Permission to enter a cell the other device has reserved |
| Deferral | A GPU sample handed to the CPU lane, re-rendered whole from its identity |
| Stand-in | A bounding primitive in the GPU scene for an entity only the CPU renders |
| Provisional sample | A GPU sample finished from a coarser texture level, to be rendered again in full |
| Generation | One pass of sampling generations: the tiles still above their target sample again |
| Pass chain | A whole adaptive frame queued on the GPU: kernels plus renders per pass |
| Parity pipeline | The older synchronous pipeline, kept as the exact reference |
| Fallback | Handing the whole scene to MoonRay XPU |
| Spec prefixes | ARC architecture, CA cellular scheduling, ACC accuracy, MBX mailbox, MEM memory, GPU and CPU lanes, THR throughput mode, VER verification |

## 13. Not done yet

From the design notes. Each has more detail where it's listed.

- Resume from a checkpoint (Continue starts again) and deep output (`FEATURE_PROGRESS.md`).
- Scene edits as change sets to both devices: refitting per changed mesh instead of rebuilding (`INDEXER.md` order,
  step 6).
- GPU program modules linked per scene by its families, and volumes and subsurface as their own continuation modules
  (`INDEXER.md` section 5).
- The GPU sampling VDB, heterogeneous and emissive volumes, points and motion itself instead of deferring them.
- Material-coherent shading on the GPU: on hold, since the profile says shadow rays dominate (`INDEXER.md` section 9).
- Cellular generations on the GPU pass chain; the adaptive chain as one CUDA graph (`ASYNC.md`).
- SIMD batches on the CPU lane; RAM-to-VRAM spill under host memory pressure (`ASYNC.md`).
- Light filters, shadow linking and lobe light sets on the GPU (they keep a scene on the CPU today).
- Remaining Modo switches: opaque alpha, transmission roughness, toon terminator, fog alpha (`FEATURE_PROGRESS.md`).

## 14. Further reading

| Document | About |
|---|---|
| [`ASYNC.md`](../interactive/ASYNC.md) | The asynchronous renderer: grid, lanes, mailbox, textures, ownership, adaptive sampling |
| [`ASYNC_RESULTS.md`](../interactive/ASYNC_RESULTS.md) | Early benchmark results and comparison images |
| [`INDEXER.md`](../interactive/INDEXER.md) | Indexer, routing, scheduling, partial shading, shadow reuse, generations, scene preparation, realtime, Modo scenes |
| [`PATH_TRACER.md`](../interactive/PATH_TRACER.md) | MoonRay's estimator, lights, materials, curves, hair, glitter, the material benchmark |
| [`FEATURE_PROGRESS.md`](../interactive/FEATURE_PROGRESS.md) | Every MoonRay feature: state and check |
| [`KIT_ROADMAP.md`](../interactive/KIT_ROADMAP.md) | XPU2 in the Modo kit: where things are, what's measured |
| [`BUILDING.md`](../interactive/BUILDING.md) | Build prerequisites and the pinned reference |
| [`feature_tests/README.md`](../interactive/feature_tests/README.md) | The feature comparison scripts |
| [`xpu2/tools/README.md`](../tools/README.md) | Kit and headless Modo tools |
