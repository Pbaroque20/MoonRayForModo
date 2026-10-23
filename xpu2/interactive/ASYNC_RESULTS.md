# XPU2 asynchronous renderer: measurements, 22 October 2026

RTX 3090 and i7-4930K (6 cores, 12 logical processors), the two synthetic fixtures of the published benchmark
(384×288, 64 samples a pixel, textured direct lighting). Original XPU is the pinned 0.4.2 runtime in fresh processes,
timed by MoonRay's own MCRT time; a warm XPU with its scene kept loaded is no faster (checked the same day). XPU2 is
timed from its first claim to the merged film on the host. Each row is the median of three after one warm-up;
nothing else rendered meanwhile. Report: `test-results/async-benchmark-6/report.json`.

| Scene | Threads | XPU | XPU2 | Less time |
| --- | --- | --- | --- | --- |
| gallery-dense | 12 | 4.154 s | 0.0220 s | 99.5% |
| gallery-dense | 1 | 26.250 s | 0.0182 s | 99.9% |
| workshop-detail | 12 | 6.978 s | 0.0277 s | 99.6% |
| workshop-detail | 1 | 44.681 s | 0.0270 s | 99.9% |

The first frame of a session, which also loads the fine-detail texture tiles it needs, took 0.029 to 0.043 s.
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

## Limits

Two synthetic scenes of the prototype's admitted domain; not a general or end-to-end claim. Images are not
byte-repeatable across runs (accumulation order varies); the parity pipeline is.
