# Bregman (working name): results

Machine: RTX 3090, i7-4930K (6 cores, 12 threads), 64 GB. Nothing else rendering during timed runs.

## Baseline: XPU2 on the overflow test scene (2026-11-19)

`MoonRayForModo-xpu2/test-results/overflow/scene.rdla`, 320 x 240. Its `pixel_samples` 8 is MoonRay's square root:
**64 samples a pixel**, exact uniform sampling (`XPU2_SESSION_UNIFORM_BUDGET=0`; unset, the worker spends uniform's
budget by sampling generations instead, which the engine's per-pixel counts turn off). XPU2's benchmark worker from
`async-build-handoff1` (GPU program sources identical to this branch's), 12 threads, CPU and GPU, three repeats:

| Run | Sampling (s) | CPU samples | GPU samples | GPU launches |
|---|---|---|---|---|
| 1 | 0.465 | 440,064 | 4,475,136 | 22 |
| 2 | 0.384 | 509,696 | 4,405,504 | 21 |
| 3 | 0.361 | 517,632 | 4,397,568 | 21 |

Preparation 1.21 s (plan 0.26 s, Embree 0.015 s, GPU lane 0.67 s, programs from OptiX's cache). About 13 million samples a
second, the GPU taking 90%.

![XPU2, 64 spp](images/xpu2-overflow-8spp.png)

`bregman/tools/run_xpu2_baseline.py --build <async build> --scene <scene> --output <new folder>`. One earlier run of
the same worker ended with "terminate called without an active exception" after printing its report (teardown, frames
whole); the script trusts a printed report with status passed and records the exit code.
