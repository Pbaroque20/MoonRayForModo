# Grouped native replay experiment

This opt-in XPU2 experiment combines completion checks for an existing bounded
packet group under one queue lock. It keeps the full numeric-input and pixel-ID
byte comparisons, frame revision and original native-owner checks, cancellation,
CPU fallback, sample math and film publication order. It does not cache native
shader pointers or move native contexts between workers.

`XPU2_REPLAY_GROUPED=1` enables the experiment. The default remains disabled.
`XPU2_REPLAY_PROFILE=<jsonl path>` records group, packet, lock, reuse and fallback
counts once per frame. Groups contain at most 16 packets. Rejected or missing
packets submit through the existing fallback path after the group lock is released.
The GPU kernel, two flight slots and four owned 64-ray chunks are unchanged.

This reduces repeated synchronization, not repeated sampler construction or
sample-packet generation. It also does not broaden GPU material coverage.

## Reproduction

Build with `tools/xpu2_native_replay_build.py`, using the frozen
`test-results/xpu2-timeline-v3-build` as `--base`, the read-only primary checkout
as `--source`, and a new isolated `--output` directory. The builder pins its
source inputs and preserves the installed runtime.

Run `tools/test_xpu2_native_replay.py` against that build and the toolchain C++
compiler. It executes the generated replay function with controlled ready,
pending, numeric/pixel mismatches, rejection, missing-ticket, exhausted-window,
mode-routing and invalid-size cases.

`tools/xpu2_native_replay_probe.py` uses the same required arguments as the timeline
probe: build, original reference runtime, previous build, PTX, previous PTX, scene
and a fresh output directory. Use `--checks` for exact-image, GPU sentinel and
failure controls; otherwise three rotated rounds plus warmups compare original
XPU, previous XPU2, same-build switch-off (`control`), and grouped replay (`four`).
Timing uses FIFO selection, one native worker, no CUDA tracing and no detailed
integration timers. `profile_control` is a profiled grouped-replay correctness
case, not a timing control.

Run `tools/xpu2_native_replay_cancel.py` with the qualified controls as `--baseline`
to test persistent cancellation and replacement. Recovery additionally exercises
bounded neighbor selection. `tools/xpu2_native_replay_evidence.py` retains source
report hashes, exact comparisons, paired timings and render-stage values.

## Validation interpretation

The first controls attempt stopped on a scheduling-dependent test expectation:
a forced input mismatch left all replacement results pending at material resume.
The image was exact, and claimed/consumed counts were both zero. The corrected
probe requires every ready result to be claimed and consumed, allows pending
results in fault cases, and still requires normal grouped renders to exercise
ready-result claiming. The initial report is preserved rather than marked passed.

The harness initially had a mixed-type C++ `auto` declaration; correcting it to
an explicit counter type allowed all 14 routing/ownership cases to pass. No
renderer change was needed for either test-harness correction.

## Results (2026-10-18)

The qualified controls, recovery and rotated timing reports contain **29 exact
float32 RGBA comparisons** against original XPU and one deliberately different
GPU sentinel. Missing PTX, zero queue capacity, injected upload failure, forced
input mismatch and forced discard all preserve the original image. Persistent
cancellation/replacement matches both a fresh candidate and original XPU, with
balanced ownership and no unretired flights. The generated-function harness
passes 14 deterministic routing/ownership cases.

In the main grouped render, 203,202 packet attempts use 22,578 replay locks;
203,013 packets reuse their saved tickets and 189 fall back. The old path takes
one readiness lock per reused ticket, so this removes about 88.9% of those
readiness-lock acquisitions. This is not a reduction in every renderer lock or
in total render cost. Numeric comparisons and original-owner checks remain.

Three rotated timing rounds after warmups, all untraced and single-worker:

- Original XPU: MCRT median 7.923 s (7.744–7.977); wall median 9.206 s.
- Previous XPU2: MCRT median 9.768 s (9.742–9.918); wall median 11.122 s.
- Same candidate, grouping off: MCRT median 9.831 s (9.782–10.397);
  wall median 11.199 s.
- Grouping on: MCRT median 9.799 s (9.709–10.055); wall median 11.204 s.

Grouped-minus-off paired MCRT differences are +0.224, +0.017 and -0.688 s
(median +0.017 s). Integration-stage paired differences have median -0.02115 s.
Thus the slightly lower difference of medians does **not** establish a speedup;
there is substantial variation, including the third off-control render. The
same-build off-control also varies against the previous binary. Do not combine
nested stage timings or differences of medians as additive costs.

Grouping remains disabled by default and is not promoted as a performance win.
The scene is one supported reflection/transmission fixture, not a production or
multiworker qualification. No competing MoonRay process was present at timing
checks before/after each render; these checks cannot exclude brief intervening
activity. No kit was installed and no user scene or shared primary source changed.

The next target remains repeated sampler/sample-packet preparation and the much
larger CPU integration workload. Reducing replay synchronization alone does not
approach the 30–40% improvement target against original XPU. The evidence file
`native-replay-20261018.json` contains report hashes, per-run stages, exact image
comparisons and paired timings. Raw reports remain under
`test-results/xpu2-replay-group-controls-v2`, `xpu2-replay-group-cancel` and
`xpu2-replay-group-timing`; the failed initial control report is retained too.
