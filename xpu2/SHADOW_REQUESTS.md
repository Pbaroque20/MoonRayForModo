# Owned shadow requests and native visibility

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

Status: **request transfer validated; CPU/GPU traversal interchangeability blocked**.
This remains an isolated XPU2 diagnostic, not a selectable or installed renderer.

## Implemented boundary

`shadow_request.h` copies surface visibility inputs into numeric owned storage:
origin, direction, near/far distances, shutter time, mask, receiver, request ID,
scene/revision identity and a light-table slot. No native light pointer or TLS
list handle travels in that request. The host resolves its light slot against a
scene/revision-scoped binding table. Invalid numeric requests, unknown lights,
wrong scenes and stale revisions are rejected before traversal.

The binding table **borrows** native light identities. It does not retain or own
MoonRay's scene. The diagnostic calls it synchronously while the native shadow
handler's scene is alive and unchanged, with fixed local scene/revision IDs.
Asynchronous integration must supply unique identities and actual scene lifetime
ownership; copying this table alone would not make migration safe.

The Windows adapter captures STANDARD queries, reverses their delivery order,
reconstructs native GPU rays, submits them through existing OptiX visibility,
and maps answers back by request ID. It also reconstructs native CPU queries.
Original visibility answers are saved for the renderer's subsequent processing,
so diagnostic queries cannot overwrite the render's results. Volumes, forced
visibility query types, contribution continuation and film/AOV publication remain
outside this boundary. This does not yet consume the preceding GPU EnvLight
prototype's outputs.

## Rendered validation — 2026-10-17

Six standalone XPU renders used the RTX 3090, one renderer thread, fixed scenes
and frozen native link objects: an unmodified reference, diagnostic build with
checks off, and checks on, for each of the normal and near-blocker fixtures.
Both trace-off and trace-on images matched every float32 RGBA pixel exactly.

- Normal fixture: 230,052 requests; 67 occluded, 229,985 visible.
- Blocker fixture: 230,243 requests; 427 occluded, 229,816 visible.
- All 460,295 requests preserved their numeric fields and original GPU results.
- All deliberately stale revisions were rejected. No valid request was rejected.
- Each fixture exercised eight batches and one light binding per batch. The
  aggregate `lights` counter sums bindings over batches, not unique scene lights.

Each fixture exposed **one CPU/GPU disagreement**. For that ray, both the copied
request and the original native CPU lookup report visible; both GPU queries
report occluded. Rechecking the original TLS light lookup reproduced the result.
Thus this is an existing backend difference, not an owned-request conversion
error. The diagnostic retains per-ray evidence locally and fails validation if
that evidence is absent or does not match the original paths.

For XPU parity, keep native GPU visibility authoritative regardless of the shading
worker. Do not silently substitute CPU traversal for these requests. This finding
does not establish the cause of the difference or approve a new ray-origin policy.

The contract executable also checks copied-state independence, distinct light
slots, missing/null bindings, scene/revision mismatch, invalid bounds, NaN/Inf,
zero directions, empty request IDs and exact preservation of signed zero and
maximum finite distance. Multiple real lights, nonzero receiver exclusions,
moving/deforming occluders and asynchronous scene replacement need further
rendered validation. This is not a speed benchmark or a clean runtime rebuild.

All 279 XPU2 regression tests pass, including nine new shadow-evidence checks.

## Reproduce

Run `tools/xpu2_shadow_request_probe.py` with `--source` pointing to the read-only
native checkout, `--frozen-build test-results/xpu2-origin-build`, and a fresh
`--output` directory. It validates frozen input hashes, preprocesses native
headers before/after compilation, builds the contract check and isolated DLL,
then renders the six comparisons. The retained origin fixtures are prerequisites.

`shadow-requests-20261017.json` records aggregate results and hashes. Captured
ray coordinates, render images, native objects and executables stay local under
`test-results/xpu2-shadow-requests-final`; no captured binary assets are published.
