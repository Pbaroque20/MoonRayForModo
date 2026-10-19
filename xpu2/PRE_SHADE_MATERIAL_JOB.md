# Bounded pre-shading material job: scope and gates

This is the next native integration target, not an implemented or qualified GPU
material backend. The first prerequisite is the measured frame-cost ceiling in
NATIVE_MATERIAL_CEILING.md. The current sampler handoff remains after material
construction. No kit installation, production default change or merge is part
of this experiment.

## Exactness is the rule

MATERIAL_JOB_GATES.json was fixed before the new frame-cost runs. One-worker
float32 RGBA must match original XPU word for word, including signed zero.
Finite checks, alpha, dimensions and metadata are mandatory. No statistical
replacement, FMA contraction, fast-math shortcut or hardware texture filtering
is permitted. Twelve-worker comparisons use the original renderer's own five
repeats and a frozen per-fixture/channel envelope; that concession to native
scheduling variation does not relax kernel or one-worker exactness.

The JSON also fixes failure/seam cases, profiling-off speed variants, five timed
repeats after warmup, a maximum of 1,024 parked points per worker / 12,288 total,
a 64 MiB total parked-state cap, and deterministic one-in-1,000 validation.
The memory cap must include continuation storage and retained flight payloads,
not just queue entries. Full CPU comparison is a debug switch, not the speed path.

## Material selected from the exporter

The actual serializer emits UsdPreviewSurface for ordinary Modo materials.
It emits DwaBaseMaterial for MoonShine overrides, glass, rough diffuse and other
advanced cases. This is an exporter branch audit, not a measured frequency
survey of user scenes. Both the experimental checkout and current primary
exporter have that ordinary/advanced distinction.

`tools/xpu2_material_export_audit.py` calls the real serializer for six cases.
The initial narrow target is its `opaque-diffuse-first-port` output:
UsdPreviewSurface, specular workflow with black specularColor, opaque, no
clearcoat, no emission, no maps/normal bindings, no layered override. This
qualifies neither the ordinary dielectric/glossy configuration nor the eight
Dwa-layer cost fixture. Those must retain their complete CPU path. The narrow
case is an integration/parity target; it cannot claim the eight-layer savings.

## Required native boundary

The insertion point is after native intersections are available and before
`shading::shadev` in ShadeBundleHandler. The old owner-chunk experiment calls
shadev while preparing every chunk, so its queue does not remove material work.
It must not be presented as the requested pre-shading queue.

Native integration subsequently reads the BSDF for light contributions, sampling,
presence/cutout, extra AOVs and additional effects. A useful accepted job must
own material evaluation **and the dependent bounded evaluation/sampling work**,
returning compact numerical results. Returning a serialized BSDF, reconstructing
an equivalent graph on the CPU, or sending CPU-computed answers for every point
would violate the intended work split. Unsupported features reject before graph
evaluation. Random sample identity must survive acceptance, rejection and replay.

A parked path also cannot retain pointers into ShadeBundleHandler's scoped arena.
The new queue needs owned intersection/continuation storage with bounded leases,
a generation-checked completion mailbox, and resume on the original native owner.
Publishing child rays/film twice is forbidden. Cancellation revokes publication
but does not release CUDA-visible storage until the device has retired it. A
queue at capacity refuses work immediately. A late fallback discards its GPU
result and performs the full CPU path once, with the same samples.

Kernel validation must use stable sample IDs rather than arrival order. A failed
spot check rejects the result and disables that kernel revision for the frame.
Already-published contributions require explicit frame invalidation/recovery if
a later spot check discovers a kernel defect; simply trusting the earlier film
would not guarantee parity. Full-check mode remains necessary for qualification.

## Texture residency and exact filtering

The existing raw OIIO mip loader and software point/bilinear CUDA filter are
reusable components, not a qualified ImageMap replacement. The filter tests use
an explicitly supplied mip. Native ImageMap also needs derivative-dependent mip
selection, anisotropy, channel/alpha/color rules, transformations and failure
semantics. Any unsupported behavior stays entirely on the CPU. Hardware texture
units remain excluded even if they look close in an image.

Materials and texture pages must use immutable scene revisions, published only
after upload completion and retained while flights reference them. Per-hit record
caching is not scene residency. The new payload size, bridge cost per point,
used/late/refused counts and no-double-work evidence have **not yet been measured**.

## Still open

- Actual native pre-shading GPU job and queue, together.
- Exact CPU/ISPC-to-CUDA material/integrator port and native software OIIO filtering.
- One-worker rendered exactness, checkerboard ownership, fault/delay/cancellation.
- Disabled overhead removal; twelve-worker enabled safety and fixed image gate.
- Profiling-off original/disabled/never-submit/always-late/normal speed matrix.
- GPU lighting remains off until its results are consumed and qualified.

No standalone queue contract, texture-filter test or cost profile closes these
native rendered-image gates.
