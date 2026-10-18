# Native neighbor scheduling and render timing

Experimental, opt-in candidate only. Existing XPU and the installed kit are
unchanged. This connects screen-space locality to the native early diffuse
queue; it does not implement whole-path CPU/GPU ownership or arbitrary
asynchronous material shading.

## Native integration

Each existing eight-lane shader packet carries the native packed pixel IDs.
A 16-pixel tile from the first active lane supplies a locality hint. Packets
spanning several tiles stay intact and are counted; lanes, sampler state,
random values and native film handling are not reordered.

The GPU worker selects its previous tile or eight neighbors from the bounded
pending queue, falling back to the oldest request. Once the oldest packet has
waited 64 selections, age takes priority over locality. The scan is bounded by
64 admitted packets and does not inspect the scene hierarchy. Selection,
cancellation and claim removal share the existing queue mutex. Scene revision,
owner checks and retained-resource credits remain enforced.

`XPU2_TILE_POLICY=neighbor` enables the policy; the default remains FIFO.
`XPU2_TILE_BATCH_LIMIT` bounds each dispatch to 1–64 packets (default 64).
The comparison uses **8 for both policies**, so locality does not receive a
different batching budget. These are experimental runtime variables, not kit
settings.

CPU-only or rejected shader work still follows the native CPU path. GPU-eligible
packets enter the existing GPU queue; this experiment changes their order,
not their device eligibility. There is no CPU stealing of in-flight GPU work.

## Measurements and checks

The separate builder compiles copied sources against the frozen reference link
inputs. The benchmark records source/runtime/PTX/scene hashes, checks actual XPU
selection, compares linear RGBA outside the timed interval, and checks GPU
consumption and clean queue teardown. Per-batch logging is disabled.

Timing uses an unmeasured first run of each configuration, followed by three
rotated-order rounds of original XPU, candidate FIFO and candidate neighbor.
Every process still initializes its own GPU context. Wall time includes process
startup and scene loading; native MCRT timing isolates the render phase.
Aggregate selection time, worker wait time, bridge execution time and scheduled
transfer payload are reported separately. Bridge time includes initialization,
copies, launch, polling, validation and reacquiring the completion lock; it is **not pure GPU kernel time**.
Payload bytes assume successful transfers; fallback controls can stop earlier.

The original native multiworker repeatability gate is still enforced at
1e-6 absolute/relative tolerance. A timing result cannot turn an image mismatch
into a pass. Fixed sampling and beauty-only diffuse fixtures do not establish
adaptive, all-material or production-scene parity.

The actual C++ policy test checks packed pixels, mixed packets, local/far FIFO
fallback, continuous-arrival aging and packet conservation. The real CUDA queue
stress harness verifies local reordering while checking reverse-order collection,
duplicate and foreign-owner rejection, retained credits, pending/worker-owned
cancellation, stale revision handling and missing-PTX fallback.

## Reproduce

- `python -m unittest discover -s tests -p test_xpu2_native_tile_policy.py -v`
- `python tools/xpu2_native_tile_build.py --source <read-only native checkout> --base <frozen origin build> --output <new isolated build>`
- `python tools/xpu2_native_tile_stress.py --source <read-only native checkout> --ptx <diffuse PTX> --output <new stress directory>`
- `python tools/xpu2_native_tile_benchmark.py --build <candidate build> --reference <frozen control runtime> --ptx <diffuse PTX> --scene <fixed diffuse RDLA> --output <new directory> --threads 1 --repeats 3`
- Add `--checks` for disabled, deliberate GPU color-change, missing-PTX and zero-capacity controls. Use `--threads 4` for the multiworker diagnostic.

Timing runs must be serial, with other rendering paused. No kit installation,
production enablement or speedup is implied by building the candidate.

## Next throughput experiment

Implemented as a separate candidate: [native batches in flight](NATIVE_FLIGHTS.md).

Keep FIFO and neighbor selection available, but replace the serial bridge drain
with a small ring of persistent pinned staging slots and independent CUDA streams.
Each slot needs its own inputs/results, completion event, scene revision and
request ownership. Submit another useful batch before waiting for a prior result;
retire completed slots without publishing cancelled or stale results, and drain
all events before releasing a frame's resources. Native CPU fallback must only
run for unaccepted or discarded work, never duplicate an accepted GPU result.

Use the same shader/sample identities, image gate and rotated timing protocol.
Compare 1, 2 and a bounded higher number of in-flight slots, including bytes moved,
batch occupancy, CPU waits, end-to-end latency and cancellation under load.
Coarser useful work matters as well: overlapping many tiny diffuse evaluations
may still cost more than the native AVX calculation. Simultaneous streams do not
guarantee concurrent hardware execution or a speedup, particularly alongside
OptiX intersection work on the same GPU.

## Observed results (RTX 3090, native AVX1, 384 x 216)

Full reports and hashes: [native-tile-scheduling-20261018.json](native-tile-scheduling-20261018.json).

- Rough diffuse, one CPU worker: median native MCRT time **3.662 s original XPU,
  14.618 s candidate FIFO, 14.487 s neighbor**. Median process times were 4.934,
  15.879 and 15.782 s. Every normal image is bitwise identical after float32
  RGBA extraction. No packets were reordered: this producer was already local.
- Mixed diffuse materials, one worker: median MCRT **3.543 / 14.785 / 14.346 s**,
  respectively. Every normal image is exact. These small timing differences do
  not establish a locality benefit or acceleration over original XPU.
- Rough diffuse, four workers: median MCRT **1.235 / 4.942 / 4.984 s**;
  median process times **2.550 / 6.289 / 6.421 s**. Neighbor mode reorders a median
  15,747 packets and reduces tile switches from 22,634 to 21,904, without a
  measured speed gain. Original XPU repeats also fail the unchanged image gate;
  **this is a failed parity diagnostic, not a validated speed comparison**.
- In the four-worker neighbor case, median aggregate selection time is 41.5 ms,
  bridge processing is 4.583 s, and the worker waits 0.276 s for queued work.
  It dispatches about 25,834 batches and schedules about 355 MB of transfers.
  These intervals are worker-side measurements, not GPU utilization or kernel-only
  time. The dominant observed cost is the serial bridge, not the local search.
- All six image controls and three actual CUDA queue stress cases pass. The
  controls cover disabled hooks, GPU color sentinel, missing PTX and capacity
  refusal. The stress cases deliberately hold the bridge before execution;
  cancellation during an actively executing CUDA kernel is not established.

This numeric shader kernel does not yet sample GPU textures, so tile locality
cannot demonstrate texture-residency savings here. Neither these small fixtures
nor the failed four-worker parity gate establish production-scene performance.
Keep the feature opt-in and the PR draft; pursue the bounded in-flight batching
experiment above before considering a scheduling default change.
