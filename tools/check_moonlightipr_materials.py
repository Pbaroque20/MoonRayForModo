"""MoonLightIPR against MoonRay on scenes captured from Modo, with Modo's own materials on them.

tools/probe_fresnel.py saves each of its scenes as the plugin read it from Modo. Each is rendered by both
engines: a ball in an even white sky, so the brightness from its middle to its edge is how much each engine
has it reflect at each angle. Usage: check_moonlightipr_materials.py <moonray-runtime> [case ...]"""
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_moonlightipr_session as fixture
import compare_moonlightipr as compare
from moonray_modo import native

source = Path(__file__).resolve().parents[1] / 'test-results/fresnel'
ANGLES = (0, 20, 40, 55, 65, 75)


def profile(values):
    """The ball's green at each angle between the view and its surface."""
    width, height = compare.WIDTH, compare.HEIGHT
    row = height // 2
    sky = values[1]
    inside = [x for x in range(width) if abs(values[(row * width + x) * 3 + 1] - sky) > .02]
    if not inside:
        return [values[(row * width + width // 2) * 3 + 1]] * len(ANGLES)
    radius, centre = (inside[-1] - inside[0] + 1) / 2.0, (inside[0] + inside[-1]) / 2.0
    found = []
    for angle in ANGLES:
        distance = radius * math.sin(math.radians(angle))
        # Along the middle row, to either side: the picture is wider than it is tall.
        places = [int(round(centre + side * distance)) for side in (-1, 1)]
        found.append(sum(values[(row * width + x) * 3 + 1] for x in places) / 2)
    return found


def main():
    runtime = native.find_runtime(sys.argv[1])
    folder = fixture.BUILD / 'compare'
    folder.mkdir(parents=True, exist_ok=True)
    os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
    report = json.loads((source / 'report.json').read_text())
    chosen = sys.argv[2:] or [case['name'] for case in report['cases'] if 'error' not in case]
    session = fixture.Session(folder)
    session.runtime = runtime
    print('%-26s %s' % ('angle from straight on', '  '.join('%5d' % a for a in ANGLES)))
    try:
        for name in chosen:
            scene = json.loads((source / (name + '.json')).read_text())
            scene['_environment'] = 0.0
            try:
                reference = compare.moonray(scene, runtime, folder, 'modo_material_' + name)
                preview, warnings = compare.moonlightipr(scene, session, 'modo_material_' + name)
            except Exception as exc:
                print('%-26s failed: %s' % (name, str(exc)[:200]))
                continue
            a, b = profile(reference), profile(preview)
            worst = max(abs(y - x) / max(x, .02) for x, y in zip(a, b))
            print('%-26s %s' % (name + ' MoonRay', '  '.join('%5.3f' % v for v in a)))
            print('%-26s %s   furthest %.0f%%' % (name + ' MoonLightIPR', '  '.join('%5.3f' % v for v in b), 100 * worst))
        session.process.stdin.write(b'quit\n')
        session.process.stdin.flush()
        session.process.wait(timeout=10)
    finally:
        if session.process.poll() is None:
            session.process.kill()


if __name__ == '__main__':
    main()
