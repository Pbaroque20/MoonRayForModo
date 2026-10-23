# XPU2: the asynchronous renderer

XPU2 renders with the CPU and the GPU working on the same image at the same time, neither waiting for the other. This
is the architecture of the Interactive xPU Renderer Spec (21 October 2026), built on the prototype's scene, sampling,
material, texture and fallback code. The earlier synchronous pipeline (`deadline_pipeline.h`) stays as the parity
build: exact shared triangle arithmetic, fixed ownership and byte-repeatable images (spec ACC-08, CPU-11).

## How a frame runs

- **Work grid** (`async_grid.h`, spec §7). The image is cut into 64×64 cells, seeded as a CPU/GPU checkerboard. Each
  cell holds its unstarted work as 16-byte chunks: one 8×8 tile and a range of sample indices, ordered by sample range
  so a cell converges evenly. A chunk is claimed exactly once, by one atomic on a cursor in host memory.
- **CPU lane** (`async_cpu.h`, §11). Persistent, pinned workers claim their own chunks by the cellular rules (§8):
  finish the cell they are in, step to the same-owner neighbour with the most unclaimed work, steal from the hottest
  opposite-owner neighbour, then drift to the hottest cell anywhere. Embree traverses native triangles in robust mode.
- **GPU lane** (`async_gpu.h`, `async_gpu.cu`, §10). Fixed-size OptiX launches (65,536 threads) over hardware
  triangles. Every thread claims one sample at a time from its launch's range with one atomic; neighbouring claims
  are neighbouring pixels of the same sample, so warps trace coherent rays. Results accumulate in a device film in
  double precision.
- **Mailbox and broker** (`async_render.h`, §8-9). The feeder thread, pinned to its own core, is the GPU's broker: it
  claims chunks for the GPU (its own cells first, then the CPU's hottest) and hands them over through a ring in
  device memory, with ownership passing at publication. It keeps two launches queued, so the GPU never waits for
  the host; it polls events, so the host never waits for the GPU (ARC-01). Launches are sized from the GPU's rate,
  timed on the device (the donation forecast, CA-08); near the end of a frame the remaining work is split so both
  devices finish together (the lookahead).
- **Textures** (§13). Host RAM holds every level of every texture and is the system of record; the CPU reads it
  directly and never misses. VRAM holds each texture's mip levels from 1 up, for the whole session, and a bounded
  cache of fine-detail (level-0) tiles, loaded on demand and evicted least recently used. A GPU sample that needs a
  tile that is not resident parks in a bounded queue on the GPU, asks for the tile once, and runs again on the GPU,
  with the same random numbers, after the tile has landed. The host sizes launches so the queue cannot overflow.
- **Ownership** (CA-10, CA-12). Cells keep their owner from frame to frame and flip towards the device that rendered
  most of them, at most 8 a frame, with a 16-frame cooldown and a 64-frame freeze after thrashing.
- **Correctness.** Every sample has a device-independent identity (pixel, index, frame), so it does not matter which
  device computes it. The shared integrator (`async_integrator.h`) is the parity pipeline's estimator, operation for
  operation. A started sample is never dropped (ACC-03). At quiescence the two films merge and every pixel's sample
  count is audited (ACC-07).

## Results

See [ASYNC_RESULTS.md](ASYNC_RESULTS.md).

## Build and run

```powershell
python xpu2/interactive/build_async.py --source $toolchainRoot --runtime $referenceRoot --output test-results/my-async-build
python xpu2/interactive/run_async_benchmark.py --build test-results/my-async-build/build.json --output test-results/my-async-benchmark
```

`async_grid_test.cc` checks the scheduler's invariants (VER-5): every chunk claimed exactly once under 12 workers and
the broker, every pixel given exactly its samples, the cellular rules, the checkerboard and the flip limits.

## Not done yet

- **Interactive frame mode** (§15): deadlines, progressive publication of the merged film, reprojection, denoising
  and display. The renderer runs in throughput mode (THR), the mode the success gate (VER-11) is measured in.
- **Spill from RAM to VRAM** under host memory pressure (MEM-06 to MEM-09). Host textures are fully decoded and never
  evicted, so there is no pressure state yet.
- **Wider native coverage.** The admitted domain is the prototype's: static triangles, diffuse and emissive
  materials, image maps and a constant environment. Everything else routes to the pinned XPU.
- **SIMD batches on the CPU lane** (CPU-03). The CPU lane traces one ray at a time; with the GPU this fast it renders
  about 1% of a frame.
- **Mapped zero-copy rings** (MBX-01). Chunks and readbacks travel by stream-ordered copies on one CUDA stream, which
  gives the same single-owner guarantees.
