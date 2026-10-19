# Bounded multi-lobe GPU material jobs

Experimental extension of the native material-admission candidate. Original XPU
and the installed Modo runtime are unchanged. The default remains one eligible
lobe when CPU lookahead is enabled.

`XPU2_MATERIAL_JOB_LOBES=2` or `4` lets one native material submission prepare
several supported lobes before resuming CPU work. The combined job is capped at
32 SIMD sample packets and each lobe at 16 packets. Existing token ownership,
full replay input comparisons, sequence seeds, numeric CUDA code, queue limits,
and native film order are retained. Unsupported lobes and excess work stay native.

A lobe is one component of a material, such as diffuse reflection or diffuse
transmission. This groups existing diffuse sampling operations; it does not
port arbitrary materials, GPU texture evaluation, or full path integration.
It does not guarantee a single CUDA launch per material: the queue still batches
ready packets independently. A four-lobe limit is not evidence of four actual
lobes on fixtures containing only two eligible lobes.

`XPU2_MATERIAL_JOB_PROFILE` writes separate record and execution counters.
Counters describe prepared lobes/packets, not successful GPU consumption. The
GPU acceptance and image-sentinel checks establish actual image contribution.
The 32-packet bound applies to the new multi-lobe option. Legacy one-lobe mode
preserves previous behavior, including its separate lookahead switch.

## Earlier admission work

`XPU2_MATERIAL_ADMISSION=supported` rejects unsupported work before payload
preparation. `cost` additionally excludes Lambert and small rough-diffuse batches;
that threshold is a hypothesis, not a calibrated hardware model. `cpu` disables
sampler offload while native GPU intersections and direct-light work can remain.
Admission defaults off. These policies do not resolve duplicated replay payloads.

The old admission instrumentation contains a comment referring to a one-worker
guard. Inspection has not established such a guard. All combined-pipeline tests
here explicitly use one native worker. In particular, the direct-light lazy queue
has a single active owner window; multiworker safety must be resolved before
broadening these tests. Passing this suite does not qualify production scenes.

## Reproduction

Build admission from the frozen `xpu2-light-lazy-v2-build` using
`tools/xpu2_native_material_admission_build.py`, then build jobs from that result
with `tools/xpu2_native_material_jobs_build.py`. Both require a read-only native
source/toolchain directory, base build, and a new isolated output directory.
They record source, linked-object and runtime hashes.

`tools/xpu2_native_material_jobs_probe.py --checks` exercises image parity,
expanded-job coverage, sampler-coordinate verification, a GPU sentinel, and
missing PTX/capacity/upload/replay failure paths. Without `--checks` it runs a
warmup and three rotated timing rounds, checking other renderer activity before
and after each run. `tools/xpu2_native_material_jobs_cancel.py` checks interrupted
persistent rendering followed by replacement and fresh/reference comparisons.
`tools/xpu2_material_job_fixtures.py` prepares rough transmission, a larger mixed
native-metal scene, and the 32-packet boundary fixture without editing user scenes.

## Validation notes

The first fault run stopped on an incorrect harness assertion equating packed
batches with successfully launched GPU flights. Missing PTX produces packed,
retired, failed batches with zero launches. The corrected validator requires
balanced retirement and bounds successful launches by the failed-batch count.
The original report and original probe sources are preserved. Its missing-PTX
image was exact; the report remains incomplete rather than being relabeled.

A second harness correction changed a stale cancellation expectation from four
owned chunks to the configured two. That attempt stopped during fresh-frame
validation, before cancellation; its report and original probe are also retained.

## Results (2026-10-19)

**28 candidate-image comparisons are exact in float32 RGBA**, including repeated
timing renders, rough reflection/transmission, mixed native metal at 512 x 288,
and the 32-packet boundary. The intentional GPU sentinel changes 45,629 pixels.
Missing PTX, zero queue capacity, injected upload failure, replay mismatch and
discard all preserve the reference image. Persistent cancellation retires all
286 sampler flights and cancels two outstanding direct-light jobs; replacement
matches both a fresh candidate and original XPU exactly.

On the main fixture, GPU-consumed sample lanes increase from 1,625,067 to
3,250,134. Execution prepares 22,585 two-lobe material jobs, and CPU lookahead
sampling drops from 203,265 packets to zero. This is sampling work, not a measure
of the GPU's percentage of total rendering time. Both one- and two-lobe modes
still use native CPU material construction, light/shadow handling and film output.

The larger jobs initially overfill speculative lookahead: one correctness run
records 42,010 queue refusals. Reducing owned chunks from four to two eliminates
these refusals in that check while retaining both GPU flight slots. Neither the
queue capacity nor the per-job 32-packet bound is enlarged. The boundary fixture
prepares exactly 32 packets per job without window overflow.

Warmup plus three rotated untraced rounds, one native worker:

- Original XPU: MCRT median **8.022 s**, range 7.863-8.286; wall median 9.682 s.
- Same candidate, one-lobe control: **11.134 s**, range 10.622-11.178; wall 12.602 s.
- Two-lobe jobs, four owned chunks: **11.958 s**, range 11.824-12.440; wall 13.427 s.
- Two-lobe jobs, two owned chunks: **11.221 s**, range 11.055-11.359; wall 12.748 s.

Reducing lookahead improves every paired two-lobe round by 0.737-1.081 s
(median 0.769 s). Against the one-lobe control, the reduced-lookahead paired
differences are +0.737, -0.123 and +0.087 s: **no established speedup**. It remains
about 3.2 s slower than original XPU on this fixture.

Preparation is still duplicated: record payload bytes grow from 162,410,400 to
324,820,800, with a similar increase at replay. The CUDA arithmetic and bytes
per sample are unchanged. Grouping more existing operations does not by itself
increase computation per transferred byte. The next useful target is retaining
prepared state and performing a more substantial supported shading stage before
returning to CPU integration, with independent parity and recovery validation.

The option remains disabled by default. No kit was installed, no original XPU
path was replaced, and no multiworker or production performance claim is made.
Before/after checks found no competing MoonRay process; they cannot exclude brief
intervening activity or unrelated system load.

[Retained reports, hashes, counters and paired timings](native-material-jobs-20261019.json).
