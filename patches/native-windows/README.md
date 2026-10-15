# Patches to OpenMoonRay for the native Windows build

These patches are applied to OpenMoonRay's own source (`sources.json` names each repository, its commit and its
patch) to build MoonRay natively on Windows with MinGW-w64 (UCRT64) for the MoonRay for Modo plugin. Most of them
are portability changes. This file explains the ones whose reason is not obvious from the diff.

## `moonray.patch`: `lib/rendering/mcrt_common/Clock.h`, the heat map's clock on Windows

### What MoonRay does

The heat map output ("time per pixel", `RenderOutput` result `RESULT_HEAT_MAP`) adds up, for every pixel, the time
spent shading the rays that land in it. The time is measured by `mcrt_common::Clock`, an RAII wrapper around
`clock_gettime()`, started and stopped around each batch of work in `RayHandlers.cc`, `ShadeBundleHandler.cc`,
`XPURayHandlers.cc` and `RenderFramePasses.cc` (through `MCRT_COMMON_CLOCK_OPEN`). Its default clock is
`CLOCK_THREAD_CPUTIME_ID`, the calling thread's CPU time. The batches are short, typically tens to hundreds of
microseconds each.

### Why that fails on Windows

On Linux, `CLOCK_THREAD_CPUTIME_ID` is accurate to nanoseconds, so each short batch is measured as it is.

On Windows, a thread's CPU time is only advanced when the scheduler's clock interrupt fires, every 15.625 ms (1/64
second) by default. `clock_gettime(CLOCK_THREAD_CPUTIME_ID)`, as the MinGW-w64 winpthreads library provides it, reads
that tick-based count. So a batch that does not straddle a tick is measured as exactly 0, and one that does is
measured as one whole tick, 15.625 ms, whatever it really took.

In the heat map that gives almost nothing. Measured on the same 160 × 120 render of a lit triangle (16 samples per
pixel, scalar mode), before and after this patch:

| | Before (`CLOCK_THREAD_CPUTIME_ID`) | After (`CLOCK_MONOTONIC`) |
|---|---|---|
| Distinct values in the heat map | 3 | 6,812 |
| Pixels reading exactly 0 | 85.6% | 0% |
| Other pixels | exactly 0.015625 s or 0.03125 s (one or two ticks) | from 0.000148 s up, in fine steps |

Before the patch, the heat map is black with scattered white dots, which are the batches that happened to straddle a
tick. It shows where the clock ticked, not where the render spent its time.

### The change

On Windows only (`#ifdef _WIN32`), `Clock`'s default clock is `CLOCK_MONOTONIC`, which winpthreads backs with
`QueryPerformanceCounter`, a counter with sub-microsecond resolution. Other platforms keep
`CLOCK_THREAD_CPUTIME_ID`, unchanged. `Clock` is used only for the heat map, so nothing else is affected.

### What it changes in meaning, and what upstream might prefer

`CLOCK_MONOTONIC` measures elapsed time between start and stop on the same thread, not CPU time. The two differ only
when the thread is preempted or blocked inside a measured batch. In a render, where the render threads are busy
shading, that is rare, and the heat map's purpose (showing which pixels are expensive relative to others) is kept.

An exact Windows equivalent of thread CPU time at high resolution exists: `QueryThreadCycleTime`, which counts the
thread's CPU cycles. It would need a conversion from cycles to seconds and a Windows-specific code path in `Clock`.
If OpenMoonRay supports Windows upstream, that, or this patch's simpler monotonic clock, is needed for the heat map
to mean anything there.

### How it was checked

- The same scene was rendered before and after, in scalar and XPU modes, and the heat map channel compared (numbers
  above).
- Every other output is unchanged: the display filter check, and a toon scene compared between MoonRay and the
  plugin's own preview renderer, give the same results as before the patch.
