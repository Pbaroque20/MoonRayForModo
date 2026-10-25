# XPU2's scene indexer: classification, routing and incremental updates

The scene index (`../indexed_scene.h`, `../rdl_scene_index.h`, `../rdl_replica.h`) captures every RDL object and
attribute of a Modo session incrementally, and the router (`routing_index.h`) keeps a decision per entity, redone only
for what an edit touched. Until now no classifier was given: every decision was "fallback", and the plan builder
(`cpu_scene.h`, `cpu::prepare`) did its own admission for the whole scene, refusing it at the first thing XPU2 does
not render, and the GPU refused whole scenes for anything its programs lack (`async_gpu.h`, `cpuOnly`).

This note is the plan to finish it.

## 1. Classification per entity

Each entity (geometry, instance, material, map, light, light filter, volume, displacement, camera) gets:

| Field | Meaning |
|---|---|
| support | `Fallback` (XPU2 does not render it: the scene goes to MoonRay XPU), `Cpu` (the CPU lane alone), `Both` |
| evidence | the conformance identity: the XPU2 feature and the comparison that verified it (for example `volume.vdb:vs1`) |
| families | the GPU feature families it needs (DwaBase, layers, hair, glitter, toon, subsurface, image maps, procedural maps, curves, points, motion, volumes, light filters, ...) |
| cost | a relative cost per hit on each device, from measured shading times per family |

The rules are the plan builder's admission, made per object so both use one source of truth: the class and attribute
checks, map bindings and their programs, and the GPU capability table (what the GPU programs implement, which is
what `cpuOnly` refuses today, family by family).

A material is classified by the shading families its BSDF tree and map graph use, so a scene with one glitter
material and many DwaBase ones is not judged by the glitter.

## 2. Routing by device

- **GPU programs by family.** The GPU program is built from the families the scene's `Both` entities use. With the
  map interpreter split into a function per map type and the families moved into separate modules, a scene compiles
  only what it uses, cached per combination.
- **Deferral to the CPU.** An entity classified `Cpu` is in the GPU scene as a stand-in: a bounding primitive (a
  moving mesh's motion bounds, a VDB's box, points' bounds) or a flag on a light or material. A GPU sample that meets
  one stops and is handed to the CPU lane, which renders that sample whole from its identity (pixel, index, frame).
  Every sample's random numbers come from its identity, so the CPU's result is the one the GPU would have made; no
  path state crosses devices, and the GPU's partial work for it is dropped (its film never sees it). The CPU lane's
  retry queue takes these samples.
- **Cells by suitability.** The work grid's cells start on the device suited to what they see: a cheap first-hit pass
  (the camera rays of one sample a tile) gives each tile the entities it sees first; a tile whose entities are `Cpu`
  or cheaper on the CPU starts CPU-owned. Ownership then follows the deferral rate: a cell whose GPU samples mostly
  defer flips to the CPU (the existing ownership flips, with deferrals counted as the CPU's).
- **Scene mode.** Any `Fallback` entity sends the scene to MoonRay XPU, with the entity and the reason, decided as
  the edit arrives instead of after a failed plan.

## 3. Incremental updates end to end

The router's change set (entities added, removed, changed, and those affected through dependencies) goes to the
renderer with the frame:

- unchanged meshes, tessellations, grids, images and light tables are reused (as today, by signature), and the
  renderer is told which ones changed instead of finding out;
- the CPU's Embree scene and the GPU's acceleration structures are refitted or rebuilt per changed mesh (instances:
  their transforms only), not rebuilt whole;
- material, light and filter records are rewritten in place where their layout allows;
- the RDLB file is written only for MoonRay's fallback, not on every edit.

## 5 in detail: the GPU program in modules

What the compile looks like now (build 74, OptiX 7.6, optimization level 3): two modules of about 10 MB of PTX each
(uniform and adaptive frames, nearly the same code), compiled in parallel, each one task on one thread for over half
an hour and about 13 GB. Marking the path tracer's big pieces `__noinline__` shrank NVRTC's work and the PTX's largest
function (integratePaths 30.8k to 12k instructions), but not OptiX's: it compiles a module's call graph as a whole.

1. **One program** for uniform and adaptive frames (the launch's adaptive flag): half the compile's CPU and memory,
   the same wall time (done, build 76).
2. **Test builds at a low optimization level** (`XPU2_OPTIX_LEVEL`, its own shader mark): GPU correctness tests
   without the hour.
3. **Families as callables in their own modules.** OptiX compiles each module on its own task, in parallel, and never
   inlines a callable into its caller. A direct callable cannot trace rays (OptiX 7.6), so the split follows what
   traces:
   - direct callables (shading, no rays): the map interpreter (a callable per map family), the material's
     parameters (resolveDwaTree, blendParameters, the hair and glitter blends), the BSDF's sample and eval per lobe
     family (base, hair, glitter, toon), the camera's ray (cameraSampleAt), the material AOVs;
   - continuation callables (they trace): subsurface (diffusion and random walk), volumes (their radiance and
     transmittance);
   - the raygen module keeps the path loop, light sampling and the traces.
   On the CPU the same calls are plain calls. A scene's pipeline links only the modules its families use (the
   indexer's families, step 1), each module compiled once and kept in OptiX's cache, so a new scene compiles at most
   the modules it adds.

   Done so far, in PTX instructions (whole, build 76 was 238k in one module):

   | Module | Callables | Build 78 | Build 81 | Next (written) |
   |---|---|---|---|---|
   | path tracer | (raygen, misses, hits) | 145k | 60k | 60k |
   | material | a hit's Bsdf, a material's presence | 85k | 85k | 12k |
   | maps | the map interpreter | 57k | 57k | 57k |
   | lights | shapes sampled, intersected, evaluated | - | 12k | 12k |
   | lobes | lobes evaluated, sampled, their albedo | - | 36k | 36k |
   | volumes | volume radiance, subsurface, shadow transmittance (continuation callables) | - | 50k | 50k |
   | DwaBase resolve | a tree's layers blended | - | - | 29k |
   | DwaBase lobes | a resolved material's lobes, glitter | - | - | 51k |

   OptiX at build 79 (four modules, the path tracer 134k): 17 of 19 compile tasks in 12 s, then the path tracer's
   module alone on one thread, past 30 minutes and 25 GB, as the whole program did before: the cost is one large
   module's, so the split continues until no module is large. Two things learned on the way: a module of callables is compiled
   relocatable (`-rdc`), or NVRTC drops its entry points; and with the materials gone NVRTC inlined 34 helpers it
   had kept as single calls (the module grew to 292k), so the big helpers are marked out of line (X2_CALL, now
   defined beside X2_HD in sample_stream.h).

## 6 in detail: where an edit's time goes now

An edit makes the plan again (meshes, grids, images and light tables reused by signature), then the CPU's Embree
scene whole, the GPU's every acceleration structure (GpuLane::prepare builds a GAS per mesh, reusing none) and a new
renderer. First steps: the GPU lane and the CPU scene keep each mesh's acceleration structure and uploaded buffers by
its MeshData (the plan builder hands an unchanged mesh's same shared object to the next plan), rebuilding only the
instance structures; the renderer keeps its ownership and lane rate across an edit of the same image size.

## 7. Scheduling: the whole picture first, important parts, rights of passage

What a preview showed before (build 86, the Modo scene of 264 classes at 1280x720, 16 samples): every chunk 4
samples, and a CPU worker finishing a cell before it moved on, so parts of the picture went to 16 samples while the
rest was black, and the whole frame was seen only once a quarter of its samples were in. The grid now (session 90):

- **Progressive order.** A uniform frame's sample ranges grow 1, 1, 2, then the chunk size, and no chunk is handed to
  a device past the least-sampled range of the cells it works without a right of passage (its frontier: its reserved
  cells and the open ones), so the faster device is never held back by the slower one's cells. The frontier moves
  when a range is handed out, not when it is done. The pictures fill the pixels no sample has reached from the finest
  level of a pyramid of averages that covers them (display only, as MoonRay's coarse passes).
- **Important parts first** (MoonRay's, `tools/port_important.py`): the pictures score each cell by the mean difference
  of its pixels' tones from their neighbours'; the cells above the mean stay their owner's (the indexer's choice,
  section 2) and may run a range ahead of the frontier; the rest are open to either device, the most important first.
  Scored at most once a second (without a watch, from pictures made for it alone).
- **Rights of passage.** A device enters a cell the other has reserved when that cannot hold the frame up: the CPU
  when one of its chunks ends well before the GPU would get through its reserved work, or when the GPU has not
  claimed for four launch windows (a latency gap); the GPU when the CPU's reserved work outlasts four of its windows,
  in a cell it would not mostly defer (the indexer's p of at least 0.2). Before the lanes' rates are measured, always.
- **Launches that fill the GPU.** A launch is sized from the GPU's measured rate (about 10 ms of work), the rate
  measured only on launches of 65,536 samples or more. A slow first launch (textures still landing, the Modo scene's
  heavy materials) made the next ones small, small ones were never measured, and the size stuck at a few thousand
  samples, a fraction of the launch's 65,536 threads: the Modo scene ran at 200,000 samples a second. Launches are now
  never below two samples a thread (session 92): that scene 74 s to 20.9 s on the GPU alone, 62 s to 19.3 s on both.
- **Cellular GPU workers.** The GPU's broker takes each launch as shares of 32 workers, each in a cell and moving by
  the same rules as a CPU worker (finish, own reserved cells, open cells, passage; neighbours first). The launch
  itself runs all at once; only where its work comes from is cellular. The outlines show them in their own colour.

## 8. Partial shading

A GPU sample that needs a fine-detail tile not yet resident is finished from the texture's next level up (levels 1
and up are always resident: the half-resolution picture and smaller, as MoonLightIPR halves textures), its tile
asked for as before. It is provisional: its value goes to the GPU's provisional film, not the film, and a record of
it (pixel, index, pass, missing tile, value) to the host. Either lane renders it again in full: the CPU lane at once
(it has every level in RAM), or the GPU once the tile has landed; its provisional value then leaves the provisional
film, and the full sample enters the film and the AOVs. The pictures show the provisional samples; the frame's end
has none left (audited), so the image stays MoonRay's. A provisional sample is not counted in its adaptive pass until
it is done in full, so the error trees never judge a low-fidelity pixel. A drain (Stop) hands out no new chunks but
renders the provisional samples in full first, then ends the frame. Never in the GPU's pass chain.

Compile time: with partial shading the maps module's OptiX compile went from 10 s to 7, then 34 and 40 minutes, its
PTX the same size each time, whether the coarser read was a retry loop, inline in each texel fetch, or a direct
callable. What those builds shared: OptiX calls in the map callable (optixGetLaunchIndex for the thread's mark, then
optixDirectCall). The textures now carry the thread's mark from where the raygen's thread is known, and the sink reads
a parent texel as a plain function (session 94).

## 9. Next: material-coherent shading on the GPU

The Modo scene above, at 640x360 on the GPU alone: 1.1 s with no bounce, 6.4 s with one, 12.6 s with four; its
subsurface makes no difference. Its 264 classes carry 489 map nodes, and a bounce ray meets any of them: a warp's
threads then run their different materials' maps one after another. MoonRay XPU queues hits by material and shades a
queue at a time (on the CPU); XPU2 is to do the same on the GPU: a bounce's hits written out, sorted by material, and
shaded in order, with the path's state in memory between the stages (a wavefront), exactly as the megakernel shades.

## Order

1. Classifier from the admission rules, with the GPU capability table; decisions shown in the session's log.
2. Scene mode from the decisions; the plan builder keeps its checks as assertions.
3. Deferral to the CPU (GPU stand-ins, deferral status, the CPU lane's retry queue), replacing `cpuOnly`.
4. Cell seeding by suitability and ownership by deferral rate.
5. GPU program families as separate modules, compiled on demand.
6. The change set to the renderer: partial rebuilds of the scene on both devices.
