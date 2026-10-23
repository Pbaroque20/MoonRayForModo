# XPU2 asynchronous renderer: measurements, 22 and 23 October 2026

RTX 3090 and i7-4930K (6 cores, 12 logical processors), the two synthetic fixtures of the published benchmark
(384×288, 64 samples a pixel, textured direct lighting). Original XPU is the pinned 0.4.2 runtime in fresh processes,
timed by MoonRay's own MCRT time; a warm XPU with its scene kept loaded is no faster (checked the same day). XPU2 is
timed from its first claim to the merged film on the host. Each row is the median of three after one warm-up;
nothing else rendered meanwhile, though on 23 October the desktop's own applications kept the GPU about 40% busy
and the times vary by a few milliseconds from run to run. Reports: `test-results/async-benchmark-8/report.json`
(23 October, the current build) and `test-results/async-benchmark-6/report.json` (22 October).

| Scene | Threads | XPU | XPU2, 23 Oct | XPU2, 22 Oct | Less time |
| --- | --- | --- | --- | --- | --- |
| gallery-dense | 12 | 4.214 s | 0.0192 s | 0.0220 s | 99.5% |
| gallery-dense | 1 | 27.022 s | 0.0171 s | 0.0182 s | 99.9% |
| workshop-detail | 12 | 6.924 s | 0.0322 s | 0.0277 s | 99.5% |
| workshop-detail | 1 | 45.474 s | 0.0243 s | 0.0270 s | 99.9% |

The first frame of a session, which also loads the fine-detail texture tiles it needs, took 0.025 to 0.063 s.
Preparation (scene read, plan, Embree and OptiX scene builds, mip upload) took 0.95 to 1.33 s and is reported apart,
as XPU's render preparation is.

## Quality gates, unchanged from the published benchmark

- **Every timed image** is at or below XPU's own 64-sample error against the 1024-sample XPU reference: relative MSE
  0.004238 against 0.004695 (gallery) and 0.003933 against 0.003966 (workshop), the same values as the parity
  pipeline, since the estimator and random numbers are the same.
- **Device split** (VER-3): CPU-only and GPU-only renders each pass, and agree within 0.0001 on every 8×8 block mean.
- **Held-out seeds** 17, 47, 101 and 151 pass.
- **1024 samples** converge to the reference: maximum pixel 0.014 and 0.017, maximum 8×8 block mean 0.0012 and
  0.0014, against limits of 0.08 and 0.015.

## Where the time goes

The GPU renders about 99% of a frame at 400 to 530 million samples a second; the CPU lane takes its share and
finishes at the same moment. A frame is the GPU's work plus about half a millisecond to bring its film to the host.
Alone, the CPU lane renders gallery-dense in 2.16 s at 12 threads, about half XPU's time, from Embree's native
triangles; the GPU alone in 0.037 s.

## Adaptive sampling

The same fixtures with MoonRay's adaptive sampling on both renderers: `sampling_mode` 2, 16 to 1024 samples a pixel,
target error 10, read after each scene. XPU's time is its MCRT time and its error the lowest of its three timed
runs; XPU2's is the median of three after one warm-up. Error is relative MSE against the same 1024-sample reference.
Report: `test-results/async-adaptive-benchmark-2/report.json`.

| Scene | Threads | XPU | XPU2, same settings | XPU2 at XPU's quality | Less time at XPU's quality |
| --- | --- | --- | --- | --- | --- |
| gallery-dense | 12 | 3.288 s, error 0.01018, 36.9 spp | 0.0473 s, 0.01231, 30.7 spp | 0.0553 s, 0.00896, 41.3 spp (target 8) | 98.3% |
| gallery-dense | 1 | 15.689 s, 0.01071, 35.3 spp | 0.0606 s, 0.01231, 30.7 spp | 0.0645 s, 0.01045, 35.7 spp (target 9) | 99.6% |
| workshop-detail | 12 | 4.094 s, 0.00897, 33.6 spp | 0.0667 s, 0.01057, 31.5 spp | 0.0837 s, 0.00757, 42.9 spp (target 8) | 98.0% |
| workshop-detail | 1 | 25.949 s, 0.00923, 32.8 spp | 0.0920 s, 0.01057, 31.5 spp | 0.1078 s, 0.00905, 36.3 spp (target 9) | 99.6% |

- **At the same target**, XPU2 gives pixels 5 to 17% fewer samples and its image error is 18 to 21% higher. The trees,
  pass schedule and stopping rule are MoonRay's, but its estimate reads XPU2's own samples, which split into even and
  odd halves differently from MoonRay's sample tables: XPU2 stops more pixels after the 19-sample stage (50,700
  against 31,100 on gallery). Pixel by pixel, where both gave a pixel the same samples, their errors are the same.
  So the table also gives the time at the target where XPU2's error is at or below XPU's.
- **The CPU alone** renders an adaptive frame in 1.27 s (gallery) and 2.18 s (workshop) at 12 threads, also less
  than XPU's time, and agrees with the GPU-only frame within 0.0042 on every 8×8 block mean.
- **Steady.** With a GPU the trees see only completed passes, so an adaptive frame's allocation does not depend on
  timing: every timed frame, here and in an earlier run of the same benchmark, had the same mean samples and the same
  error to six places.
- **Where the time goes.** An adaptive frame is a chain of 32 passes, each waiting for the trees built from the one
  before. The GPU's samples take about 8 ms of a gallery frame; the rest is about a millisecond a pass: the pass's
  launch and readback, the error launch, 0.3 ms of tree building (9 ms a frame on gallery, 13 to 15 ms on workshop),
  and making the next pass.
- **Not checked here:** held-out seeds and a 1024-sample convergence run for adaptive frames; those gates are the
  uniform benchmark's.

## Limits

Two synthetic scenes of the prototype's admitted domain; not a general or end-to-end claim. Images are not
byte-repeatable across runs (accumulation order varies); the parity pipeline is.
