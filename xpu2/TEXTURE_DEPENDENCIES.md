# Scene-index texture dependencies

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

`texture_dependencies.h` projects owned scene-index shader references into shared
texture resources and their material users. `rdl_texture_dependencies.h` supplies
native RDL filename metadata and layer/geometry/part/material assignments. This
is an isolated native integration; the persistent renderer has not been wired to
this projection yet.

## Data and updates

A resolver maps a filename attribute to verified canonical asset identities,
explicit content revisions and raw-decoding interpretations. The projection walks
the indexed references, including attribute bindings and intermediate maps, with
cycle protection. Identical resources are counted once across materials. Different
content revisions and interpretations remain distinct. Layer and part identities
are retained, even when two layers assign the same geometry differently.

Changed source slots and scene-index notifications invalidate their transitive
material consumers using both old and new reverse edges. Only affected material
closures are rebuilt; unchanged material records retain their immutable storage.
Transform-only edits do not traverse material graphs. Assignment-only changes
identify affected geometry without reloading its texture data. These affected
objects represent shading/assignment invalidation, not every geometry edit in the
underlying SceneIndex change set.

The resulting snapshot reports affected materials/objects and resources whose
reference counts enter or leave the material index. Retired resources are no
longer demanded by that snapshot; **this does not force eviction or cancel active
readers**. Old snapshots and leased cache pages retain the old revisions. All
materials are indexed, including currently unassigned materials. Actual sampled
tile demand must come from the renderer, not from eagerly loading this entire list.

Preparation does not publish data. `publishDependencies` checks both the committed
scene view and a separate dependency-base token. The latter rejects stale updates
when a file revision changes without any native scene attribute changing. The
coordinator must acknowledge native application and commit the matching scene
before publishing; no active native scene is mutated by the projection itself.

`indexedTileRequests` converts an explicitly requested mip/tile into existing
residency-policy requests, preserving sharing across material users. The sampler
still chooses mip/tiles and validates their dimensions. Unreferenced demands and
materials with unresolved sources are rejected rather than declared GPU-ready.
This index does not establish shader/device capability or select CPU fallback.

## Native discovery and limits

The adapter reads filename-flagged attributes on RDL Map/NormalMap objects, plus
surface-material assignments on Layers. Static string filenames are supported;
other filename types or motion-sampled filename attributes are unresolved. Empty
strings are represented as no file dependency, not evidence of a supported shader.
The resolver must explicitly expand UDIM/sequence patterns or mark them unresolved.
This probe deliberately rejects those patterns and missing files. Native default-
color behavior for missing textures remains a shader concern; it is not emulated.

Metadata discovery and the probe resolver's OIIO metadata registration remain
synchronous. Discovery currently scans native objects; source and assignment
catalogs are supplied as complete owned maps, while material closures update
incrementally. This is not yet incremental file discovery, automatic file watching,
content hashing, a measured load-time optimization or a full scene dependency
solution. Light/environment, displacement/volume roots and instance-specific
material overrides beyond captured Layer assignments require further integration.

## Validation

- **4,030 assertions / 1,000 content-revision updates**: shared resource accounting,
  exact tile demands, retained readers, no-op/transform reuse, assignment changes,
  detach/remove, material removal, missing and partially resolved sources, cycles,
  malformed input, and stale publication rejection.
- Existing cache, residency-policy and asynchronous-loader contracts also passed:
  29,532, 74,689 and 1,292 assertions respectively.
- **Eight native RDL stages / 32 assertions**: initial shared ImageMap, idle capture,
  geometry transform, external declared content revision, shader unbinding, layer
  part reassignment, filename edit and missing/UDIM-path rejection.
- Native metadata feeds the owned index, shared residency requests and background
  OIIO decoding. **Three loaded tiles matched synchronous OIIO bytes exactly**;
  an old cache lease remained valid across a revision change. The revision-change
  case advances the declared identity without altering the immutable fixture file.

These are native scene-reader and decoded-byte checks, **not rendered-image parity,
GPU sampling integration or a speed benchmark**. Existing XPU and installed kits
are unchanged. No Modo instance or user scene was opened.

Compact evidence: `texture-dependencies-20261017.json`.

```powershell
python tools/xpu2_texture_cache_probe.py --source <read-only-toolchain-root> --output <new-directory>
python tools/xpu2_texture_dependencies_probe.py --source <read-only-native-root> --runtime <frozen-runtime> --fixtures <passed-OIIO-probe-directory> --output <new-directory>
```

Next: incremental native metadata discovery, validated asset manifests, pending
request cancellation tied to scene generations, and a native dispatcher that
continues ready work while requested pages decode/upload.
