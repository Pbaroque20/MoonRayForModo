"""Write local evidence summary only after bounded test reports exist."""

import json

from pathlib import Path

from reference_runtime import sha

P=Path(__file__).resolve().parent;TR=P.parents[1]/'test-results'

r=json.loads((TR/'interactive-residency-benchmark-20261022/report.json').read_text());a=json.loads((TR/'interactive-estimator-ablation-20261022/report.json').read_text());e=json.loads((TR/'interactive-reference-padded-20261022/report.json').read_text())

lines=['# Private XPU2 texture residency and larger-scene evidence â€” 2026-10-22','',

'All changes, sources, images and reports remain local and ignored. No kit installation, reference-runtime modification, public commit, push or production default change.', '',

'## Implementation', '',

'An opt-in fine cache coalesces a GPU texture miss into one asynchronous full-mip upload. Existing paths keep their GPU state and old descriptors until an exclusive pause; once the new immutable texture view is ready, they resume at shading with the same sample identity. CPU queues continue. Geometry and materials are reused. A path that still misses after one retry takes the existing validated CPU continuation route. No coarse substitute or duplicate graph evaluation is used.', '',

'The cache is bounded to 64 MiB texels; existing 256 MiB device and 64 MiB pinned-memory limits remain. This is a whole-mip refill with synchronous host packing/allocation followed by asynchronous copies, not a selective page-demand/LRU cache or fully asynchronous preparation. Warm frames reuse uploaded textures. No hardware texture filtering, fast-math or sampling changes were introduced.', '',

'An independent optional 33 ms display cadence avoids copying the full film every 2 ms scheduling window. Work continues between display updates. The final film is unchanged. This is display throttling, not dirty-rectangle transfer. Both controls are opt-in; CPU/GPU assignment remains fixed 50/50, with no untouched-work donation.', '',

'## Render measurements', '',

'RTX 3090, i7-4930K (6 physical/12 logical cores). Same 64 spp, raw linear float32 quality metrics, no denoising. Four renders per arm, first discarded for warm medians. Native retains resources; original runs in fresh processes with warmed OS/driver caches. Original medians come from the earlier same-session test; a new 12-thread control records timing drift separately. No external profiler. These are render-phase times, not complete startup/scene-loading claims.', '']

for name,c in r['cases'].items():

 ar=c['arms'];lines.append('### '+name);lines.append('')

 for t in (1,12):

  n=ar['t%d-r1-p33'%t];o=c['original'][str(t)]['sampling_seconds'];s=n['sampling_seconds'];lines.append('- %d threads: original XPU %.3f s; updated XPU2 %.3f s (%.3fâ€“%.3f), %.1f%% lower warm median.'%(t,o['median'],s['median'],s['min'],s['max'],100*c['warm_savings_vs_xpu'][str(t)]))

 lines.append('- 12-thread factorial: unchanged %.3f s; display cadence only %.3f s; fine residency only %.3f s; both %.3f s.'%tuple(ar[k]['sampling_seconds']['median'] for k in ('t12-r0-p0','t12-r0-p33','t12-r1-p0','t12-r1-p33')))

 n=ar['t12-r1-p33'];first=n['runs'][0];lines.append('- Preparation %.3f s; first render including refill %.3f s; fine texels %.2f MiB; GPU-completed sample share 50%%. No texture migrations or warm GPU allocations.'%(n['prepare_seconds'],first['sampling_seconds'],n['active_texture_bytes']/2**20))

 hi=c['high_spp'];err=hi.get('runs',[{}])[0].get('error',{});lines.append('- Fixed 64-spp target %g; held-out seed/high-spp checks %s. 1024-spp max channel %s, max 8x8 block bias %s. Largest pixel delta between ownership/display arms: %g.'%(c['target'],c['quality_passed'],err.get('max_pixel'),err.get('max_block_mean'),c['image_delta_between_arms']))

 lines.append('- Fresh original-XPU 12-thread control: %.3f s, %.3f times the earlier median.'%(c['fresh_reference_control']['stats']['Mcrt time (s)'],c['fresh_reference_control']['relative_timing_to_prior']));lines.append('')

lines+=['The first small post-build pilot incurred 33.5 seconds of GPU preparation (cold process/driver compilation costs were not separately instrumented); the later timing runs used a warmed driver cache. Do not interpret warm speedups as a first-ever-launch guarantee. The old default-cache dense high-spp and workshop one-thread watchdog failures remain in the original report; the new bounded candidate does not erase those failures.', '',

'## Noise-source ablation', '',

'Camera samples, intersections and material evaluations are shared across all six component-test variants. Only directional sampling and the light estimator vary. BSDF-only uses cosine-weighted sampling; two-BSDF and BSDF+uniform-environment power-MIS each make two directional attempts. MIS is an experimental test implementation, not an exact MoonRay estimator port. It is not installed into the production path.', '']

for name,c in a.get('cases',{}).items():

 lines.append('- '+name+': median relative MSE '+', '.join(k+'='+format(v,'.7g') for k,v in c['median_relative_mse'].items())+'.')

lines+=['', '## Strict ownership check', '', 'The .002 internal maximum-channel check does not pass on these larger scenes: gallery has 8 outlier pixels (maximum .00418563), workshop 6 (maximum .00735882). The benchmark reportâ€™s all_quality_gates_passed field covers statistical reference targets and high-spp image gates only; qualification-addendum.json records the missing stricter check explicitly. Native qualification is false. Display-cadence changes and 1/12 worker counts are byte-identical within a fixed ownership mode. The selected-path diagnostic shows differing primary hit triangles or shadow-ray origins; continuing the GPU shading state through CPU visibility reproduces its GPU result on all sampled outliers. This does not justify changing the bound. Robust-traversal diagnostics are separate from the timed candidate.', '', '## Reference envelope', '',

'Original XPU accumulation was not patched. A new explicitly empirical guardband uses max(2 times reference-only channel range, 8 float32 epsilon times max(1, reference peak)); all bounds were frozen before fresh held-out tests. Historical failed originals/fallbacks are explicitly calibration now, not reused as new held-out evidence. Native quality gates remain unchanged.', '', 'New reference-only guardband status: '+e['status']+'.']

for t,c in e.get('cases',{}).items():lines.append('- '+t+' threads: bound '+str(c.get('frozen_bound'))+'; '+str(len(c.get('heldout',[])))+' fresh original renders and '+str(len(c.get('fallback',[])))+' fresh fallback renders. RGB/alpha negative controls rejected: '+str(c.get('negative_rgb_control_rejected') and c.get('negative_alpha_control_rejected'))+'.')

lines+=['', 'This is a tested-fixture rounding allowance, not a proof of a universal bound or restored bitwise repeatability. Prior unpadded failures remain unchanged.', '',

'## Safety and limits', '',

'Recovery tests exercise GPU-only and mixed ownership at 1/12 threads, warm cache reuse, tiny-cache retry/fallback, cancellation on first refill, stale/corrupt/replayed handoff rejection, invalid result rejection, and recovery. Maximum CPU-oracle image delta was below 2e-6 against the unchanged .002 internal gate. Worker-count pairs were byte-identical. A first harness attempt wrongly expected a fine-cache refill from a scene that never requested one; that failed report is retained, and the corrected miss fixture passed.', '',

'These synthetic tests admit flat triangle geometry, diffuse/emission USD Preview materials, ImageMaps and a constant environment, with direct illumination only. They do not establish arbitrary Modo/material/lighting parity, secondary textured derivatives, production reliability, scene-load improvement, or general 30â€“50% speedup. Native output remains tier D and unqualified. CPU/GPU donation, demand-selected pages, shared-page eviction and wider material/light coverage remain future work.', '',

'## Evidence', '',

'- ../../test-results/interactive-large-benchmark-20261022/report.json (preserved previous failures)',

'- ../../test-results/interactive-residency-benchmark-20261022/report.json (factorial, raw images, seeds, 1/12 threads)',

'- ../../test-results/interactive-residency-recovery-20261022b/report.json (new refill recovery)',

'- ../../test-results/interactive-estimator-ablation-20261022/report.json (noise component test)',

'- ../../test-results/interactive-residency-ownership-20261022/report.json (strict ownership failure and stage diagnosis)',

'- ../../test-results/interactive-residency-controller-20261022/report.json (private controller options and fallback)',

'- ../../test-results/interactive-residency-legacy-regression-20261022/report.json (unchanged default path)',

'- ../../test-results/interactive-reference-padded-20261022/report.json (new reference-only held-outs)',

'- ../../test-results/interactive-residency-benchmark-20261022/images/manifest.json (identical display transforms and raw provenance)', '']

(P/'RESULTS_20261022_RESIDENCY.md').write_text('\n'.join(lines),encoding='utf-8');print('Local report written')
