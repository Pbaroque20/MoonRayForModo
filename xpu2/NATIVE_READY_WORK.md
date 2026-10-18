# Native lobe lookahead and shared shader inputs

This isolated candidate extends [grouped packets](NATIVE_BATCH_GROUPS.md). It is
opt-in, keeps original XPU intact, and does not install or enable an XPU2 renderer.

## Independent ready work

`XPU2_LOBE_LOOKAHEAD=1` prepares up to two eligible BSDF lobes before consuming the
first result. Each lobe retains its original eight-lane grouping, sampler seed,
sample number, native owner and eventual film order. Preparation uses separate
sampler state; the native loop still advances its own sampler exactly as before.
The per-lane active-lobe seed is reproduced, including skipped/unsupported lobes.

The bound is two lobes with at most sixteen packets each. Each packet has its own
queue ticket and revision. Existing capacity limits still apply and refused work
falls back to native shading. The remaining lobes use the ordinary on-demand path.
This exposes independent work within a native shading call. It is not suspension
of entire paths, cross-worker arena migration, or integration of the separate
owned-child continuation prototype. A single-lobe scene cannot acquire another
independent lobe through this change.

## More shading per upload

`XPU2_SHARED_INPUTS=1` lets multiple samples reuse the same invariant input record.
Within a batch, each lane compares its invariant fields with the previous packet's
same lane. Matching records share the invariant block; each sample sends an index
and its two random values. Comparisons are bitwise and bounded linear work. The
GPU reconstructs the original 96-byte record before running unchanged diffuse math.

For n sample lanes and k unique records, the upload is 8 + 12n + 96k bytes,
instead of 100n bytes. If this is not smaller, that batch uses the original layout.
The compact path also replaces two upload calls with one. Both readbacks remain:
96 bytes of full input echo and 36 bytes of result per lane. The host verifies the
entire echo against the original input before accepting a result. This reduces
bytes per existing shading operation; it adds no new material family or shader
operation and removes no numerical/identity validation.

Pinned compact staging and device memory belong to each flight slot until its
completion event retires. Cancellation, revision checks, exactly-once collection,
error draining and native fallback remain in force. A PTX without the compact
entry point fails initialization and retains native CPU results. The new PTX also
contains the original entry point for explicit uncompressed comparisons.

## Validation protocol

The build copies native sources and links against frozen retained inputs. The
CUDA compile preserves strict arithmetic flags and records source/PTX identities.
The actual queue checks cover zero/partial/full admission, copied caller storage,
foreign/stale/duplicate tokens, cancellation, missing PTX and slot cleanup.

Native controls compare original XPU, disabled hooks, the previous grouped runtime,
the new runtime with both changes off, lookahead only, shared inputs only, both,
a deliberate GPU color change, missing/mismatched PTX, capacity zero and failure
after upload. Normal images use the unchanged 1e-6 float32 RGBA gate; exactness is
recorded separately. The sentinel must visibly change the image. Family/sample
counts and scheduled transfer bytes distinguish real GPU work from fallback.

Timing uses one warmup and three rotated measured rounds for the seven configurations (reference, previous, current, lookahead, shared, combined,
and combined with a 32-packet limit), one native worker and two available flights.
The first six use a sixteen-packet limit. Image
extraction is outside the timed interval. Source, runtime and GPU identity checks
surround every matrix. Persistent cancellation/reload uses the combined path.

No multiworker parity, hardware saturation, simultaneous kernel execution or
production device-loss recovery is implied. The prior native multiworker
repeatability failure, including original XPU repetitions, remains unresolved.

## Results: RTX 3090 / AVX1, 2026-10-18

The reflection/transmission fixture is 384 x 216. One warmup and three measured
rounds per configuration produced **28 exactly matching float32 RGBA images**.
All candidate runs consumed **3,250,134 GPU lanes**, with the same fallback count
and no capacity refusals. The scene has two eligible diffuse lobes; this is not a
single-lobe or general production speed claim.

Median MCRT (range), seconds:

- Original XPU: **8.636** (7.560-8.695).
- Previous grouped candidate, limit 16: **21.400** (17.809-22.266).
- New candidate with both changes off: **22.467** (19.156-23.173).
- Lookahead only, limit 16: **16.266** (16.138-17.646).
- Shared inputs only, limit 16: **22.817** (22.716-23.326).
- Both, limit 16: **18.405** (18.389-19.188).
- Both, limit 32: **16.870** (15.346-17.719).

Lookahead alone has the best median: **24.0% shorter MCRT** and **22.0% shorter
process time** versus the previous candidate (22.718 -> 17.712 s process).
The best single run belongs to the combined/32 case; three repetitions with
overlapping ranges do not establish a universal winner. Original XPU still wins
by a large margin. The new disabled-feature control is also slightly slower than
the previous candidate at its median, with overlapping ranges; that overhead is
reported rather than hidden by comparing only against the new control.

Lookahead increases ready packets from 9 to 18 and occupied slots from 1 to 2.
It does not manufacture extra samples, change sample selection or move native
arenas. GPU kernels running simultaneously is not established by occupied slots.

Scheduled transfer volume is **754,519,680 bytes** without shared inputs,
**503,374,480** with sharing alone, a median **520,337,008** for both/16, and
**503,185,016** for both/32. These include uploads and both diagnostic readbacks;
they are scheduled bytes, not measured PCIe bandwidth. Shared inputs save roughly
31-33% overall transfer volume, but add packing/decoding work and show no clear
render-time advantage over lookahead alone in this fixture. Keep sharing opt-in.

The first five candidate configurations dispatch 45,170 batches. Both/32 drops
the median to 22,891. This again shows why fewer bytes or dispatches alone do not
prove faster rendering; useful overlap and preparation costs also matter.

For the next experimental comparison, use `XPU2_GROUP_PACKETS=1`,
`XPU2_INFLIGHT_BATCHES=2`, `XPU2_TILE_BATCH_LIMIT=16`,
`XPU2_LOBE_LOOKAHEAD=1`, and leave `XPU2_SHARED_INPUTS` off. Set sharing to `1`
only for explicit transfer experiments, optionally comparing a limit of 32.
All flags remain opt-in; the installed kit and original XPU are unchanged.

Twelve native controls pass, including exact normal images, a deliberately
changed GPU sentinel, missing PTX, the old PTX lacking the compact entry point,
zero capacity and partial-upload failure fallback. Five group-admission cases
and three actual-CUDA queue regressions pass. The held-stream test cancels four
incomplete compact flights, retains their resources until release, publishes no
cancelled results and frees all slot allocations. It does not cancel a kernel
while that kernel is actively executing.

Persistent fresh and cancel/reload checks pass, including exact final RGBA versus
original XPU and between fresh/restarted candidate frames. All 182 submitted
flights of the cancelled frame and all 44,958 of the replacement frame retire.
No requests, compact allocations or stale outputs remain. A separate twelve-case
mixed-material matrix also passes with exact normal/fallback images, covering
rough diffuse and changing lobe masks. This completes the mixed-scene validation
that was deferred in the previous batch-group experiment due to external load.

Full reports, hashes and individual timing samples are retained in
[native-ready-work-20261018.json](native-ready-work-20261018.json).
