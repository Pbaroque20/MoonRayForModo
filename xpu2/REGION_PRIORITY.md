# Region hierarchy and importance scheduling

The approved direction reuses the idea behind Modo's "important parts first":
prioritize image regions without losing coverage. The existing native implementation
in RenderFramePasses.cc ranks tiles by neighboring-pixel luminance contrast and
moves above-average tiles first. That is a priority heuristic, not a noise estimate
or a convergence decision. It remains unchanged by this experiment.

`region_priority.py` adds an immutable sparse quadtree over image tiles. Its leaves
receive normalized noise and contrast priorities, a changed-region flag, and an
age in checkpoint epochs. Parent priority is the maximum child priority. Traversal
visits higher-priority subregions first, retaining Morton order for ties. Aging
can outweigh the bounded visual score. These provisional weights are a scheduling
policy to measure, not a perceptual error metric or production tuning result.

`MortonPlan` accepts an explicit tile ordering, validates coverage and rejects
duplicates/out-of-image tiles. `AdaptiveMortonSchedule` can change this ordering
only when advancing from a complete checkpoint. Pixel/sample addresses remain
fixed. Every still-active pixel receives its prescribed sample interval; priority
never removes a pixel or lowers its sampling cap. Native estimator decisions must
still arrive independently. Changes in visual priority must not themselves mark
pixels converged or reset accumulated samples.

`choose_device` first filters required capabilities, then compares measured cost
inputs: queued work, launch overhead, transfers and execution cost. It can prefer
CPU work when GPU transfers/queueing outweigh compute savings. Missing resources
or unsupported capabilities return no device: the work stays pending. CPU/GPU
workers should claim independent eligible work concurrently; there is no mandatory
GPU-first phase, fixed 50/50 split or permanent device ownership by screen region.

This is a **Python scheduling/cost-policy model**. Device names in its tests are
simulated workers. The native dispatcher still needs capability enforcement,
resource leases, live timing feedback, coherent batching and dynamic queue updates.
The GPU cannot yet independently execute arbitrary MoonRay paths. CPU-only shader
work must retain an explicit fallback, without mixing approximate shading into the
reference film. The native adaptive estimator, reconstruction-filter overlap and
native priority-tree dispatch are not integrated by this change.

The 13 focused checks cover sparse/edge tiles, hierarchy coverage, stable Morton
ties, immutable signals, aging, noisy-flat versus clean-edge priority, capability
and cost routing, missing-resource deferral, invalid inputs, and transactional
reprioritization. The model produces identical weighted images, sample addresses
and counts with priority enabled/disabled and CPU/GPU completions interleaved.
This does not establish native adaptive RGB parity or a rendering speedup.

```powershell
python -m unittest discover -s tests -p "test_xpu2*priority.py" -v
python -m unittest discover -s tests -p "test_xpu2*.py"
```

Next integration: consume immutable native checkpoint statistics, measure per-work
costs, and pass eligible packets through the existing bounded native queue. Keep
whole-render XPU fallback until native image and lifetime gates pass.

The full XPU2 regression suite passed: 368 tests in 44.873 seconds. The compact
source/log fingerprint record is `region-priority-20261017.json`.
