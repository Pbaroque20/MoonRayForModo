# Native shadow work during GPU material waits

> **Historical first attempt.** This report belongs to the native-bridge research that began with the October 16, 2026 tests. It does not describe the newer standalone prototype. See the [current prototype](interactive/README.md), [current validation](interactive/VALIDATION.md), or [historical research index](RESEARCH_INDEX.md).

XPU2 remains an isolated experiment alongside XPU. This candidate is opt-in,
not installed, and is not full asynchronous arbitrary-material shading.

## Why the earlier helper failed

The original native queue helper could flush local, shadow and intersection
queues while a material sample was pending. Explicit shading-attribute context
preservation did not fix its maximum red error of 0.05917731.

Two further diagnostic builds separate the causes without relaxing the image gate:

- Forcing small ray batches to the GPU keeps intersection and shadow traversal at
  100%, but still produces maximum red error 0.05917731. Backend switching alone
  does not explain the larger error.
- Local queues alone pass the 1e-6 absolute/relative gate (maximum RGB error
  2.98023224e-8). Shadow-only helping using native routing fails at 6.78747892e-5.
  Its GPU shadow percentage falls to 14.39%.
- Intersection-only helping fails at 0.05917734. Restricting help to GPU-sized
  ray batches also fails at 0.05917731. Queue size alone is insufficient.
- Shadow-only helping with GPU routing passes (maximum RGB error 2.08616257e-7).
  It processes 5,494,492 shadow entries with 3,250,134 accepted GPU material lanes
  and no recursively entered material helper. It is not bitwise identical.

These controlled ablations locate the major failure in early intersection/shading
work. They do not yet identify the exact native sampling/context defect. Both
intersection-helper variants remain rejected. Changing traversal backend also
causes a smaller, separately observed shadow discrepancy on this fixture.

## Scoped implementation

`native_shadow_work.py` derives the guarded material-wait hook from the split
material stage. It performs only pending XPU shadow work. It never explicitly
flushes intersection/shading or local film queues. The waiting material owner,
its arena, BSDFs and sampler remain on their original thread and stack.

A thread-local RAII guard marks only the dynamic helper call. While it is active,
`RenderDriver::flushXPUQueues` skips the intersection queue, and the shadow queue
may use the GPU below the normal 1,024-ray threshold. The existing busy-device
admission guard remains. Outside the helper, native size thresholds and normal
frame-drain behavior are unchanged. There is no global small-batch routing switch
in this candidate. The shading-attribute table is saved, cleared and restored;
cancellation and stack-depth checks precede helping. Recursive helping is refused.

Enable in the isolated runtime with the existing supported GPU-material settings,
`XPU2_MATERIAL_STAGE=lights` and `XPU2_MATERIAL_HELP=1`. These flags default off.
Adaptive sampling and AOV-bearing frames retain the existing native admission
bypass. No native pointer or live BSDF crosses the GPU queue.

## Validation boundaries

The accepted gate is 1e-6 absolute/relative linear float32 RGBA. Exact comparison
is recorded separately; reordered shadow contributions can change accumulation
rounding. A deliberate GPU-color sentinel must change the image. Missing PTX,
zero capacity and upload failure must exercise CPU fallback and retire ownership.
Persistent cancellation/reload and adaptive bypass are separate checks.

The implementation remains a supported diffuse-sampling experiment. It does not
execute arbitrary materials, texture graphs or complete native paths on the GPU.
Multiworker parity, complex shadow materials/volumes, busy-device fallback and
broader scene/AOV behavior are unqualified. The native GPU shadow handler still
waits synchronously for traversal; calling it with material jobs pending does not
prove simultaneous CUDA kernel execution. No speedup over XPU is claimed.

## Reproduce

Use fresh output directories and the frozen retained reference/link inputs:

    python tools/xpu2_native_shadow_work_build.py --source <primary-read-only> --base test-results/xpu2-origin-build --output <build>
    python tools/xpu2_native_shadow_work_probe.py --build <build> --reference test-results/xpu2-origin-build/control --ptx test-results/xpu2-native-work-ptx/film.ptx --previous test-results/xpu2-native-work-build --previous-ptx test-results/xpu2-native-work-ptx/film.ptx --scene <fixture.rdla> --output <controls> --checks

The probe also supports a rotated timing sweep without `--checks`, and adaptive
admission checks with `--checks --bypass`. It records source/runtime identities,
image differences, GPU consumption, stage balance, helping and flight retirement.
Do not mix the rejected queue-isolation runtime with the scoped implementation.

## Completed image and recovery checks

Both eight-case matrices pass on the scoped build: reflection/transmission and
mixed rough materials. All fourteen normal/fallback images pass the unchanged
RGB gate; both intentional GPU-color sentinels visibly differ. Enabled helper
maximum RGB errors are 2.08616257e-7 and 3.57627869e-7 respectively; alpha is exact.
The enabled cases consume 3,250,134 and 1,621,368 GPU material lanes and process
5,494,492 and 2,808,908 shadow entries. There are no nested helper calls or leaked
flight credits. Stage-disabled controls remain bitwise identical to XPU.

Persistent fresh and cancel/reload images pass against XPU and each other. The
cancelled frame performs 103 helper calls / 18,668 shadow entries and balances
91 material calls/resumes; the completed replacement balances 22,479 calls.
This tests interrupted frame recovery, not forced interruption inside an active
CUDA kernel. Adaptive bypass is bitwise identical with zero helper calls, stage
calls, or GPU material lanes.

## Next investigation

Early intersection/shading work remains disallowed until native path/sample
identity survives queue regrouping. Shadow overlap alone does not complete that
continuation boundary. The generated shading bridge also still creates its own
CUDA context with `cuCtxCreate_v2`, while native OptiX uses its current CUDA
context. Shared-context lifetime management is a separate candidate to measure;
no cost or speedup has been attributed to that difference yet.

## Timing result

Three rotated measured rounds after warmup pass all twelve image comparisons.
MCRT medians are **7.277 s original XPU**, **16.251 s split material stage**,
and **18.679 s scoped shadow helping**. Helping is **14.9% slower** than
stage-only on this fixture; it is not a throughput optimization. Small shadow
launches and separate context execution are investigation targets, not measured
causal attributions. The helper remains experimental and off by default.

Full reports, source/runtime identities and rejected comparisons:
[native-shadow-work-20261018.json](native-shadow-work-20261018.json).
