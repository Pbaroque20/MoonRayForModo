# Native scene index: incremental attributes and retained metadata

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

The index now captures native RDL attributes and reconstructs a separate native
SceneContext. Transform, material, deformation and binding edits prepare only
changed attributes; unchanged geometry and metadata branches stay shared.
This is an isolated adapter, not an installed XPU2 renderer.

`rdl_scene_index.h` encodes every native RDL attribute type, both motion time steps,
object references and shader bindings into owned bytes. Objects and attributes
have separate stable IDs derived from native object names and attribute names.
Object names are identities: renaming requires remove/recreate. Native class
metadata is retained even when classification uses a broad category. The native
source still scans objects for dirty flags; unchanged attributes are not encoded.
Binding update bits can survive native commit, so cached binding identities are
compared before treating those flags as changes.

`rdl_replica.h` requires the candidate's exact acknowledged base. It constructs
objects before resolving references, validates changed attributes, then applies
them to its private context. A mutation failure invalidates that replica; the
committed index remains unchanged and a full rebuild restores it. Incremental
native removal requires a rebuild. This replica is not shared with active render
workers; production mutation must first drain those workers.

The codec is internal to the same native build, not a portable archive format.
RDLB remains the archive format. Native references are names, never borrowed
pointers. Pixel textures, procedural results, BVHs and device allocations are not
owned or streamed by this adapter yet.

## Metadata optimization

`persistent_map.h` provides immutable AVL maps. Snapshot copies retain a root;
edits copy only the affected tree paths. Kind and dependency sets are coalesced
per transaction, and unchanged dependencies skip reverse-edge updates. This
removes the previous whole-map copy from small updates. High-fanout dependency
invalidation still costs proportionally to affected consumers. Budgets remain
logical per-snapshot limits, not total process/VRAM memory limits.

Three paired runs on 10,001 synthetic entities measured a transform transaction
at 7.2-7.4 microseconds median, versus 1.86-1.89 milliseconds for b01f841. Both
prepared the same 128 bytes and retained the same 1 MiB geometry. These numbers
measure metadata bookkeeping only, not scene loading or rendering acceleration.

## Image and failure validation

26 native XPU renders passed, with 14 exact finite RGBA comparisons:
- Six source/indexed pairs on a small scene, plus original RDLA versus its indexed
  initial image.
- The same checks on a pinned dense scene with 131,584 vertices and 131,072 quads.
- Every edit visibly changed the image. All native attribute values, references,
  bindings and motion samples also matched.

The dense initial capture encoded 4,219,707 bytes. Transform and material edits
encoded only 304 and 67 bytes; deformation encoded only its changed position
attribute (1,579,067 bytes). Binding and unbinding were checked independently.
Malformed payload and foreign-base rejection were exercised, followed by recovery.

The optimized core passed 49 native assertions, 80,000 concurrent snapshot reads,
and two real CUDA jobs with 16 accepted samples and zero mismatches. The AVL map
stress test covered 30,000 random edits and retained-reader snapshots. The preceding
355 Python regressions were unchanged by this native-only follow-up.

All image comparisons used one native XPU worker and the retained RTX 3090
reference runtime. This does not certify multi-worker repeatability, adaptive
parity, full GPU shading, or faster first-scene loading. Each validation image
still started a native renderer process from an RDLB snapshot. Integrating these
updates into a running renderer is the next step.

## Reproduce

```powershell
python tools/xpu2_index_benchmark.py --source <read-only-native-root> --output <new-directory>
python tools/xpu2_rdl_index_probe.py --source <read-only-native-root> --runtime <reference-runtime> --scene <fixture.rdla> --output <new-directory> --render
python tools/xpu2_rdl_index_replay.py --build <passed-probe-directory> --runtime <reference-runtime> --scene <dense.rdla> --scene-lock <reference.json> --output <new-directory>
```

Use fixtures containing `/modo/mesh/0` and `/modo/material/1` with a diffuse-color
material and nonempty vertex positions. The scripts reject source/runtime drift.
Sanitized results are in `native-scene-index-20261017.json`; full local evidence is
under `test-results/xpu2-rdl-index-sixth`, `xpu2-rdl-original-small`,
`xpu2-rdl-index-dense`, `xpu2-index-optimized-final`, and
`xpu2-index-benchmark-final`. No shared checkout, installed kit or user scene was
modified.
