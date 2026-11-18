"""Render each orthographic camera of tools/probe_cl_ortho_camera.py as the plugin exported it with MoonRay, and find
the three markers in Modo's render and in MoonRay's: where the red one is (from the picture's middle, as a share of its
width and height), and how far the green and blue ones are from it (as a share of the width), which says how wide the
camera sees. Usage: check_ortho_camera.py <runtime> [variant ...] [--moonlightipr: MoonLightIPR's saved pictures in
place of MoonRay's]"""
import json
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))
from check_fresnel import pixels  # noqa: E402  (sets the plugin's modules up without Modo)
from moonray_modo import native  # noqa: E402

folder = root / 'test-results/ortho-camera'


def markers(picture):
    """Each marker's middle, in pixels, from the pixels where its own colour leads."""
    width, height, values = picture
    found = {}
    for y in range(height):
        for x in range(width):
            rgb = values[(y * width + x) * 3:(y * width + x) * 3 + 3]
            top, low = max(rgb), min(rgb)
            # A marker's pixels are well saturated (a view transform's tints aside); the grey around them is not.
            if top < 0.05 or top - low < 0.4 * top:
                continue
            name = ('red', 'green', 'blue')[rgb.index(top)]
            held = found.setdefault(name, [0.0, 0.0, 0])
            held[0] += x; held[1] += y; held[2] += 1
    return {name: (sx / n, sy / n, n) for name, (sx, sy, n) in found.items()}, width, height


def describe(found, width, height):
    if 'red' not in found:
        return 'no red marker'
    rx, ry, _ = found['red']
    text = 'red at %+.3f %+.3f' % ((rx - width / 2) / width, (height / 2 - ry) / height)
    for name in ('green', 'blue'):
        if name in found:
            gx, gy, _ = found[name]
            text += ', %s %.3f away' % (name, ((gx - rx) ** 2 + (gy - ry) ** 2) ** .5 / width)
        else:
            text += ', no %s' % name
    return text + ' (%dx%d)' % (width, height)


runtime = native.find_runtime(sys.argv[1])
report = json.loads((folder / 'report.json').read_text())
asked = [a for a in sys.argv[2:] if a != '--moonlightipr']
if '--moonlightipr' in sys.argv:
    # MoonLightIPR's pictures, saved in a test Modo (tools/probe_gui_item_mask_kinds.py, one scene a variant), against Modo's.
    for name in asked or list(report['variants']):
        picture = folder / ('moonlightipr_%s.png' % name)
        if not picture.is_file():
            continue
        modo = next(folder.glob('modo_%s*.exr' % name))
        print('%-13s width %.4f' % (name, report['variants'][name]['plugin width']))
        print('   Modo         ' + describe(*markers(pixels(runtime, modo))))
        print('   MoonLightIPR ' + describe(*markers(pixels(runtime, picture))))
    raise SystemExit
for name in asked or list(report['variants']):
    output = folder / ('moonray_%s.exr' % name)
    done = subprocess.run([str(runtime / 'moonray.exe'), '-in', str(folder / (name + '.rdla')), '-out', str(output), '-exec_mode', 'scalar'],
                          env=native.environment(runtime), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if done.returncode or not output.is_file():
        print('%-9s MoonRay did not render: %s' % (name, done.stdout.decode(errors='replace')[-300:]))
        continue
    modo = next(folder.glob('modo_%s*.exr' % name))
    print('%-9s width %.4f' % (name, report['variants'][name]['plugin width']))
    print('   Modo    ' + describe(*markers(pixels(runtime, modo))))
    print('   MoonRay ' + describe(*markers(pixels(runtime, output))))
