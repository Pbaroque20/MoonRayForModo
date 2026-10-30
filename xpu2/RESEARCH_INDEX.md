# First-attempt research index

[Back to XPU2](README.md) | [Current prototype](interactive/README.md) | [Current validation](interactive/VALIDATION.md)

**Historical first attempt, not current prototype documentation.** The October 16 tests began the native MoonRay bridge approach. Its subsequent reports below record that same earlier effort, even when written later. The newer standalone implementation and its October 22 evidence are in `interactive/`.

These reports preserve successful checks, failed gates, performance limitations and abandoned approaches. Their original acceptance rules and “next step” statements are historical, not requirements or claims for the newer work.

## Browse by topic

- [First-attempt scope and acceptance](#first-attempt-scope-and-acceptance)
- [Reference images, repeatability and sampling](#reference-images-repeatability-and-sampling)
- [Scene indexing, resources and textures](#scene-indexing-resources-and-textures)
- [Profiling, costs and overhead](#profiling-costs-and-overhead)
- [GPU transport, residency and batching](#gpu-transport-residency-and-batching)
- [Queues, ownership and scheduling](#queues-ownership-and-scheduling)
- [Materials, lighting and film integration](#materials-lighting-and-film-integration)

## First-attempt scope and acceptance

- [Bounded pre-shading material job: scope and gates](PRE_SHADE_MATERIAL_JOB.md)
- [XPU2 architecture acceptance criteria](XPU2_ACCEPTANCE.md)

## Reference images, repeatability and sampling

- [Where the selected-pixel difference is amplified](CONTRIBUTIONS.md)
- [Correlated native sampler and Lambert state](CORRELATED_STATE.md)
- [CUDA sampler subset: first real GPU validation](CUDA_SAMPLER.md)
- [Experimental CUDA sampler notices](CUDA_SAMPLER_LICENSES.md)
- [CUDA cache-boundary validation](CUDA_WINDOW.md)
- [CUDA distribution sampler validation](DISTRIBUTIONS.md)
- [Native CPU / CUDA sampler handoffs](EXCHANGE.md)
- [First CUDA shading evaluation: Lambert](LAMBERT.md)
- [Lambert direction sampling: C++ agreement, AVX8 parity blocked](LAMBERT_SAMPLE.md)
- [AVX8-compatible Lambert sampling](LAMBERT_VECTOR.md)
- [Native numeric surface-state capture](NATIVE_SURFACE_STATE.md)
- [Copied-ray origin candidates](ORIGINS.md)
- [Ray-traced shading migration fixture](RAY_IMAGE.md)
- [XPU reference repeatability — October 16, 2026](REPEATABILITY.md)
- [Native sampler reference](SAMPLER.md)
- [Selected-ray CPU/OptiX comparison](SELECTED_RAYS.md)
- [Combined sampling and shading handoff](SHADING_EXCHANGE.md)
- [Native sampler cache-window boundary](WINDOW.md)

## Scene indexing, resources and textures

- [Indexed scene resources and Morton convergence checkpoints](INDEXED_SCENE.md)
- [Native scene lifetime: delayed OptiX work and drains](NATIVE_SCENE_DRAIN.md)
- [Native scene index: incremental attributes and retained metadata](NATIVE_SCENE_INDEX.md)
- [Persistent native scene-index bridge](RDL_LIVE_INDEX.md)
- [Scene lifetime gate with retained GPU jobs](SCENE_LIFETIME.md)
- [Background texture decoding](TEXTURE_ASYNC.md)
- [Bounded RAM / VRAM texture-tile cache](TEXTURE_CACHE.md)
- [Scene-index texture dependencies](TEXTURE_DEPENDENCIES.md)
- [CUDA point and bilinear texture filtering](TEXTURE_FILTER.md)
- [Native OIIO mip loading](TEXTURE_OIIO.md)
- [Texture residency policy and hierarchy](TEXTURE_RESIDENCY.md)
- [Texture-ready work dispatch](TEXTURE_WORK.md)

## Profiling, costs and overhead

- [Native chunk and offload attribution](NATIVE_ATTRIBUTION.md)
- [Native CPU shading cost versus bridge cost](NATIVE_CPU_COST.md)
- [Exclusive bridge-stage cost diagnostic](NATIVE_EXCLUSIVE_PROFILE.md)
- [Native integration profiling and completion waits](NATIVE_INTEGRATION_PROFILE.md)
- [Native material frame-cost ceilings](NATIVE_MATERIAL_CEILING.md)
- [Rough-diffuse algebra experiment](NATIVE_MATH_SHORTCUT.md)
- [Host overhead and shared-data experiment](NATIVE_OVERHEAD.md)
- [Native synchronous/asynchronous timeline diagnostic](NATIVE_TIMELINE.md)
- [Native shading overhead measurements](PROFILING.md)

## GPU transport, residency and batching

- [Pinned asynchronous transfers](ASYNC_TRANSFERS.md)
- [Bounded native shading batches](BATCHED_SHADING.md)
- [Live film transfers and CUDA graph replay](FILM_TRANSFERS.md)
- [Local coordination and larger GPU batches](LOCAL_BATCHES.md)
- [Grouped native shading packets](NATIVE_BATCH_GROUPS.md)
- [Exact-image 64-ray native chunk qualification](NATIVE_CHUNK64.md)
- [Shared-context diagnostic and batch-layer preparation](NATIVE_CONTEXT.md)
- [Native transfer efficiency and independent CPU shading](NATIVE_EFFICIENCY.md)
- [Bounded native batches in flight](NATIVE_FLIGHTS.md)
- [Native input preparation experiment](NATIVE_INPUT_PREPARATION.md)
- [Early shared host shading records](NATIVE_PREPARED_RECORDS.md)
- [Per-flight resident GPU shading records](NATIVE_RESIDENT_RECORDS.md)
- [Resident record review fixes](NATIVE_RESIDENT_REVIEW.md)
- [Native batch transport integration](NATIVE_TRANSPORT.md)
- [Bounded native shading windows and chunk size](NATIVE_WIDE_WINDOWS.md)
- [Combined readback and shader-audit controls](PACKED_READBACK.md)
- [Explicit native sample-window dispatch](WINDOW_DISPATCH.md)

## Queues, ownership and scheduling

- [Alternating CPU/GPU workers](ALTERNATING_WORKERS.md)
- [Nonblocking GPU queue tickets](ASYNC_QUEUE.md)
- [Owned CPU-resume stage](CONTINUATIONS.md)
- [Dedicated native GPU queue during active rendering](DEDICATED_QUEUE.md)
- [Neighbor-first tile scheduling experiment](LOCAL_TILE_SCHEDULING.md)
- [Native coordination overhead experiment](NATIVE_COORDINATION.md)
- [Bounded local-neighbor scheduling](NATIVE_LOCAL_NEIGHBOR.md)
- [Opportunistic no-wait GPU shading](NATIVE_NO_WAIT.md)
- [Owner-thread native chunk preparation](NATIVE_OWNED_CHUNKS.md)
- [Rolling owner-scoped shading queue](NATIVE_OWNER_STAGE.md)
- [Native queued Lambert shading diagnostic](NATIVE_QUEUE.md)
- [Grouped native replay experiment](NATIVE_REPLAY.md)
- [Native neighbor scheduling and render timing](NATIVE_TILE_SCHEDULING.md)
- [Region hierarchy and importance scheduling](REGION_PRIORITY.md)
- [Deterministic XPU2 work scheduling](SCHEDULING.md)
- [Independent CPU work during GPU dispatch](SCHEDULING_OVERLAP.md)

## Materials, lighting and film integration

- [Broader native GPU diffuse shading](BROADER_DIFFUSE.md)
- [Coalescing live contribution jobs across native workers](COALESCED_FILM.md)
- [Native split-phase Lambert handoff](DEFERRED_SHADING.md)
- [Live GPU contribution results in native rendered images](FILM_IMAGE.md)
- [Live contribution-window batching](FILM_WINDOWS.md)
- [Fused Lambert sampling and contribution arithmetic](FUSED_CONTRIBUTION.md)
- [Live environment evaluation on the GPU](LIVE_ENV.md)
- [Live fused Lambert and contribution dispatch](LIVE_FUSED_FILM.md)
- [Native asynchronous direct-light replacement](NATIVE_DIRECT_LIGHT_ASYNC.md)
- [Larger GPU direct-light unit](NATIVE_DIRECT_LIGHT_UNIT.md)
- [Native terminal-radiance suspension and film resumption](NATIVE_FILM_CONTINUATIONS.md)
- [Native asynchronous GPU shading](NATIVE_GPU_SHADING.md)
- [Native XPU shading integration diagnostic](NATIVE_INTEGRATION.md)
- [Grouped native light-sample packets](NATIVE_LIGHT_GROUPS.md)
- [Descriptor-first direct-light scheduling](NATIVE_LIGHT_LAZY.md)
- [Native lighting work during GPU dispatch](NATIVE_LIGHT_OVERLAP.md)
- [Alternating device preferences and untouched-work stealing](NATIVE_LIGHT_TILE_CLAIMS.md)
- [Bounded multi-lobe GPU material jobs](NATIVE_MATERIAL_JOBS.md)
- [Split native material sampling stage](NATIVE_MATERIAL_STAGE.md)
- [Bounded native material lookahead](NATIVE_MATERIAL_WINDOW.md)
- [Native first-bounce path restoration](NATIVE_PATH_RESTORE.md)
- [Native lobe lookahead and shared shader inputs](NATIVE_READY_WORK.md)
- [Resume sample-coordinate reuse](NATIVE_SAMPLE_REUSE.md)
- [Numeric native sampler cache](NATIVE_SAMPLER_CACHE.md)
- [Native shadow work during GPU material waits](NATIVE_SHADOW_WORK.md)
- [Owned native contribution arithmetic](OWNED_CONTRIBUTION.md)
- [Owned asynchronous shading-stage dispatch](SHADING_DISPATCH.md)
- [Owned shadow requests and native visibility](SHADOW_REQUESTS.md)
