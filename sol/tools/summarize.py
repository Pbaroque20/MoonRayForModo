"""One line per engine run: median times, errors against the reference, XPU2's frames beside it.

summarize.py <run_sol output> [...]"""
import json
import sys
from pathlib import Path

for d in sys.argv[1:]:
    r = json.loads((Path(d) / 'report.json').read_text(encoding='utf-8'))
    m, e, o = r['median_seconds'], r.get('errors', {}), r['options']
    g = r.get('geometric_error', {})
    line = (f"{Path(d).name}: engine {m['engine']:.3f}s (geom {m.get('geometry', 0):.3f} p1 {m['phase1']:.3f} "
            f"region {m['region']:.3f} p2 {m['phase2']:.3f}) probes {r.get('probes', 0)} trusted {r['classes'].get('trusted', 0):.3f} "
            f"geomerr p99 {g.get('relative_error_p99', 0):.1e} wrong {g.get('other_mesh_seen', 0)}/{g.get('background_hits_geometry', 0)} "
            f"relMSE {e['final']['relative_mse']:.3e} (phase2 {e['phase2']['relative_mse']:.3e}) "
            f"block {e['final']['block_error']:.2e} ratio {e['final']['mean_ratio']:.5f} | "
            f"spp2 {r['phase2_samples_per_pixel']:.2f}")
    xs = sorted((k for k in m if k.startswith('xpu2-')), key=lambda k: int(k[5:]))
    if xs:
        line += ' | XPU2' + (f"+qmc{o.get('xpu2_qmc')}" if o.get('xpu2_qmc') else '') + ' ' + '  '.join(
            f"{k[5:]}: {m[k]:.3f}s {e[k]['relative_mse']:.2e}" for k in xs)
    print(line)
