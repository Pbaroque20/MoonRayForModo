"""Render a captured scene (tools/probe_cl_rdl_snapshot.py) in MoonRay and MoonLightIPR, compare their brightness, and
follow the MoonLightIPR session's memory over repeated scene loads.

Usage: compare_rdl_snapshot.py <moonray-runtime> [name] [width height]
Writes test-results/rdl-compare/<name>_moonray_left_moonlightipr_right.ppm and <name>.compare.json."""
import json
import pathlib
import pickle
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
import compare_moonlightipr as compare
from moonray_modo import native

runtime = native.find_runtime(sys.argv[1])
name = sys.argv[2] if len(sys.argv) > 2 else 'coffee_maker'
width, height = (int(sys.argv[3]), int(sys.argv[4])) if len(sys.argv) > 4 else (400, 500)
folder = ROOT / 'test-results/rdl-compare'
scene = pickle.loads((folder / (name + '.snapshot.pickle')).read_bytes())
compare.WIDTH, compare.HEIGHT = width, height
compare.fixture.WIDTH, compare.fixture.HEIGHT = width, height    # the session takes pictures of this size
compare.os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)


def working_set(pid):
    """The process's memory in use, in MB, as Task Manager's Memory column shows it (private working set)."""
    out = subprocess.run(['powershell', '-NoProfile', '-Command', '(Get-Process -Id %d).PrivateMemorySize64' % pid],
                         capture_output=True, text=True).stdout.strip()
    return round(int(out) / 2 ** 20, 1) if out.isdigit() else None


report = {'name': name, 'size': [width, height], 'runtime': str(runtime)}
started = time.time()
reference = compare.moonray(scene, runtime, folder, name)
report['moonray_seconds'] = round(time.time() - started, 1)
session = compare.fixture.Session(folder)
session.runtime = runtime
try:
    started = time.time()
    preview, warnings = compare.moonlightipr(scene, session, name)
    report['moonlightipr_seconds'] = round(time.time() - started, 1)
    report['moonlightipr_warnings'] = warnings
    a, b = compare.blocks(reference), compare.blocks(preview)
    lit = [(x, y) for x, y in zip(a, b) if x > 1e-3] or [(1.0, 0.0)]
    ratios = sorted(y / x for x, y in lit)
    report['mean_ratio'] = sum(b) / max(sum(a), 1e-12)
    report['median_tile_ratio'] = ratios[len(ratios) // 2]
    report['tiles_within_10_percent'] = sum(1 for r in ratios if .9 <= r <= 1.1) / len(ratios)
    report['moonray_mean'], report['moonlightipr_mean'] = sum(a) / len(a), sum(b) / len(b)
    compare.write_ppm(folder / (name + '_moonray_left_moonlightipr_right.ppm'), reference, preview)
    # Memory over repeated loads: every other load asks for the meshes again, as after a scene change.
    memory = [working_set(session.process.pid)]
    for i in range(10):
        if i % 2 == 0:
            session.known = ()
        compare.moonlightipr(scene, session, name + '_again')
        memory.append(working_set(session.process.pid))
    report['moonlightipr_session_memory_mb'] = memory
    session.process.stdin.write(b'quit\n')
    session.process.stdin.flush()
    session.process.wait(timeout=10)
finally:
    if session.process.poll() is None:
        session.process.kill()
(folder / (name + '.compare.json')).write_text(json.dumps(report, indent=1, default=str), encoding='utf-8')
print(json.dumps({k: v for k, v in report.items() if k != 'moonlightipr_warnings'}, indent=1, default=str))
