# Persistent native scene-index bridge

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

The isolated runtime now applies indexed attribute deltas to a stopped native
RenderContext, retaining its index between frames. It is enabled only by
`XPU2_RDL_INDEX=1` in the diagnostic build. Stock XPU and the installed kit are
unchanged.

On the first delta, the bridge captures the current native scene into owned
buffers and constructs a proxy input context. Later deltas update that proxy,
encode only changed attributes, prepare a candidate, and apply its changed
attributes to the native renderer. Native dirty flags remain set for startFrame,
so normal native shader, geometry and accelerator preparation still runs.

The bridge preserves the existing incoming delta transport (file or shared-memory
RDLA, or the binary update overload). It does not send a complete scene through a
file for each edit. It also does not eliminate existing input delta parsing or
initial scene loading. The current proxy and owned index duplicate some RAM data;
this is a correctness integration, not yet a net preparation-time improvement.

Only the native coordinator invokes these hooks, after rendering has stopped.
Mutation failures mark the context invalid and reject subsequent starts/updates.
Recovery requires recreating the RenderContext. Teardown discards the index; a
full reload starts fresh. Direct geometry updates invalidate the retained index.
Other out-of-band native mutations are outside this diagnostic contract.

## Validation

On the small fixture, three persistent sessions each rendered nine frames:
initial, transform, material, deformation, binding, unbinding, repeated no-op,
full reload, then another transform. All 18 control/indexed comparisons to stock
XPU matched exactly in finite RGBA, using one native worker. Reload/no-op images
also matched their earlier frames exactly. The index encoded only one attribute
for each transform, material and deformation change; the repeated delta encoded
zero. Full reload rebuilt the index rather than reusing a stale revision.

The dense 131,584-vertex fixture passed the same nine-frame sequence on all three
runtimes. Across small and dense scenes, 54 frames completed and all 36 cross-runtime
RGBA comparisons were exact. Dense deformation encoded only 1,579,067 position
bytes; transform/material edits encoded 304/67 bytes and no-op encoded zero.
The dense trace measured about 71-80 ms for initial index/proxy setup and 15.5 ms
for deformation read/capture/preparation/application combined. Dense full-frame
completion remained around 5-6 seconds across reference and candidate; these
single ordered runs establish correctness, not rendering acceleration.

The first index initialization took about 49-50 ms in that run. Subsequent
transform/material capture, preparation and application together took fractions
of a millisecond. These are single-run diagnostic counters, not a claimed
end-to-end speedup. The native renderer still performs its normal geometry and
GPU accelerator updates.

A separate native contract check verifies rejection during active rendering,
preservation of native dirty flags, no-op snapshot reuse, failure after a partial
proxy read, rejection of later starts/updates, release on teardown and exact
rebuild from a known-good target. The previous private-replica check additionally
covers truncated attribute payload failure.

An earlier disabled-bridge session stalled during GPU accelerator creation after
a full reload. Its renderer was terminated at the probe timeout. A complete rerun
passed all three sessions; the intermittent stall is retained as an unresolved
runtime/driver observation, not claimed fixed or attributed to the index.
Evidence: `test-results/xpu2-rdl-live-first/control/render.log` and
`test-results/xpu2-rdl-live-retry/report.json`.

## Reproduce

```powershell
python tools/xpu2_rdl_live_build.py --source <read-only-native-root> --frozen-build <retained-native-build> --output <new-build>
python tools/xpu2_rdl_live_probe.py --source <read-only-native-root> --build <new-build> --reference <reference-runtime> --fixtures <passed-rdl-index-probe> --output <new-results>
python tools/xpu2_rdl_live_contract.py --source <read-only-native-root> --runtime <new-build/runtime> --scene <initial-source.rdlb> --output <new-contract-results>
```

The builder instruments a copy of RenderContext.cc and links retained native
objects. It does not edit native sources or the protected persistent session
implementation. This is not a clean native-source rebuild. Validation currently
uses binary delta files through the filename overload; the in-memory binary
update hook and direct geometry invalidation hook are compiled but not separately
exercised by these render sessions. Adaptive/multi-worker parity, native Morton
work ownership, independent GPU full-path shading, texture paging, JIT geometry
and Modo integration remain unfinished.

Compact evidence: `rdl-live-index-20261017.json`. Dense local results are in
`test-results/xpu2-rdl-live-dense`; native failure checks are in
`test-results/xpu2-rdl-live-contract-v2`.
