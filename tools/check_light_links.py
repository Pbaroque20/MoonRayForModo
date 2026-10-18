"""Render light links with MoonRay and see that they hold: what lights a linked object, and what does not.

Two triangles side by side, each lit straight on by a key light (intensity 1) and a fill (0.25). Rendered three ways:
unlinked; the left triangle linked to the fill alone (Restrict illumination to checked lights), where it should keep a
fifth of its light and the right one all of it; and the left triangle set not to receive the key's shadow, where both
keep all their light (nothing casts one here). Printed: each triangle's brightness against the unlinked render.
Usage: check_light_links.py <moonray-runtime>"""
import copy
import json
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))
from check_fresnel import pixels  # noqa: E402  (also sets the plugin's modules up without Modo)
from moonray_modo import native, rdla  # noqa: E402

folder = root / 'test-results/light-links'
SIZE = (160, 80)


def scene():
    def triangle(identity, x):
        return {'name': identity, 'identity': identity, 'vertices': [[x - .8, -.8, 0], [x + .8, -.8, 0], [x, .8, 0]], 'faces': [[0, 1, 2]],
                'matrix': rdla.IDENTITY}
    return {'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 4, 1], 'focal_mm': 35, 'film_mm': 36},
            'materials': {'': {'color': [.8, .8, .8], 'roughness': .9}},
            'meshes': [triangle('left', -1.0), triangle('right', 1.0)],
            'lights': [{'identity': 'key', 'name': 'Key', 'kind': 'DistantLight', 'color': [1, 1, 1], 'intensity': 1.0, 'matrix': rdla.IDENTITY},
                       {'identity': 'fill', 'name': 'Fill', 'kind': 'DistantLight', 'color': [1, 1, 1], 'intensity': .25, 'matrix': rdla.IDENTITY}]}


def render(runtime, name, value):
    output = folder / (name + '.exr')
    (folder / (name + '.rdla')).write_text(rdla.scene_text(value, SIZE[0], SIZE[1], 4, 0.0, str(output)), encoding='utf-8')
    done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(folder / (name + '.rdla'), output, 0, 'vectorized'),
                          env=native.environment(runtime), cwd=str(folder), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if done.returncode or not output.is_file():
        raise SystemExit('%s: MoonRay failed: %s' % (name, done.stdout.decode(errors='replace')[-400:]))
    width, height, values = pixels(runtime, output)
    def mean(x0, x1):
        found = [values[(y * width + x) * 3 + 1] for y in range(height // 3, 2 * height // 3) for x in range(x0, x1)]
        return sum(found) / len(found)
    # The middle of each triangle.
    return mean(width // 4 - 6, width // 4 + 6), mean(3 * width // 4 - 6, 3 * width // 4 + 6)


def main():
    runtime = Path(sys.argv[1]).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    plain = render(runtime, 'unlinked', scene())
    linked = scene()
    linked['production'] = {'objects': {'left': {'link_enabled': True, 'lights': ['fill']}}}
    restricted = render(runtime, 'left_fill_only', linked)
    shadowless = scene()
    shadowless['production'] = {'objects': {'left': {'shadow_exclude': ['key']}}}
    unshadowed = render(runtime, 'left_no_key_shadow', shadowless)
    print('unlinked            left %.3f  right %.3f' % plain)
    for label, got, wanted in (('left lit by fill only', restricted, (.2, 1.0)), ('left no key shadow', unshadowed, (1.0, 1.0))):
        ratio = (got[0] / plain[0], got[1] / plain[1])
        ok = all(abs(r - w) < .03 for r, w in zip(ratio, wanted))
        print('%-20s left %.3f  right %.3f   (wanted %.2f and %.2f)  %s' % ((label,) + ratio + wanted + ('ok' if ok else 'WRONG',)))


if __name__ == '__main__':
    main()
