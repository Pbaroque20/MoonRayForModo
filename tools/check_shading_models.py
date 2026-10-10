"""Hold MoonLightIPR against Modo's own renders of each of its shading models, and find what matches each best.

Usage: check_shading_models.py <moonray-runtime> [fit]
Reads test-results/shading-models, which tools/probe_shading_models.py makes. Without fit, each case is drawn as the
plugin now translates it and set beside Modo's picture. With fit, each highlight-only case is drawn with both of
MoonLightIPR's specular lobes over a range of roughness, and the closest of them is printed: that is where the
plugin's rule for each shading model comes from."""
import copy
import json
import math
import pathlib
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
from moonray_modo import moonlightipr_scene, native
import check_moonlightipr_session as fixture

FOLDER = ROOT / 'test-results/shading-models'
WIDTH, HEIGHT, SAMPLES = 320, 180, 128
# MoonLightIPR draws at the size its test session is made for, a whole number of times Modo's picture.
SCALE = fixture.WIDTH // WIDTH
assert fixture.WIDTH == WIDTH * SCALE and fixture.HEIGHT == HEIGHT * SCALE


def modo_picture(runtime, name):
    source = next(FOLDER.glob('modo_%s.*.exr' % name))
    target = FOLDER / ('modo_%s.pfm' % name)
    if not target.is_file() or target.stat().st_mtime < source.stat().st_mtime:
        subprocess.run([str(runtime / 'oiiotool.exe'), str(source), '--ch', 'R,G,B', '-d', 'float', '-o', str(target)],
                       env=native.environment(runtime), check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    data = target.read_bytes()
    header = data.split(b'\n', 3)
    return struct.unpack(('<' if float(header[2]) < 0 else '>') + '%df' % (WIDTH * HEIGHT * 3), header[3])


def drawn(session, scene):
    payload, keys, warnings = moonlightipr_scene.pack(scene, fixture.WIDTH, fixture.HEIGHT, 0.0, session.known, SAMPLES, denoise=False, runtime=session.runtime)
    session.send(payload)
    result = session.wait()
    if result['event'] != 'DONE':
        raise RuntimeError('MoonLightIPR rejected the scene')
    session.known = keys
    return struct.unpack('<%df' % (fixture.WIDTH * fixture.HEIGHT * 3), result['pixels'])


def tiles(values, size=4):
    """Mean brightness of small squares, which takes the noise out without losing a highlight's shape. The squares
    cover the same part of the picture whichever of the two sizes it was drawn at."""
    scale = SCALE if len(values) == fixture.WIDTH * fixture.HEIGHT * 3 else 1
    width, height, size = WIDTH * scale, HEIGHT * scale, size * scale
    columns, rows = width // size, height // size
    sums = [0.0] * (columns * rows)
    for y in range(rows * size):
        row = values[y * width * 3:(y + 1) * width * 3]
        for x in range(columns * size):
            sums[(y // size) * columns + x // size] += .2126 * row[x * 3] + .7152 * row[x * 3 + 1] + .0722 * row[x * 3 + 2]
    return [v / (size * size) for v in sums]


def apart(theirs, ours, shaped=False):
    """How far two pictures are apart: the mean difference of their squares, as a share of Modo's mean. With shaped,
    ours is first made as bright as Modo's overall, which leaves the shape of the highlight to be compared."""
    a, b = tiles(theirs), tiles(ours)
    scale = sum(a) / max(sum(b), 1e-9) if shaped else 1.0
    return sum(abs(x - y * scale) for x, y in zip(a, b)) / max(sum(a), 1e-9)


def with_material(scene, materials, **changes):
    changed = copy.deepcopy(materials)
    for material in changed.values():
        for row in [material] + list(material.get('material_stack') or []):
            row.update(changes)
    return dict(scene, materials=changed)


def main():
    runtime = native.find_runtime(sys.argv[1])
    fit = 'fit' in sys.argv[2:]
    report = json.loads((FOLDER / 'report.json').read_text())
    scene = json.loads((FOLDER / 'scene.json').read_text())
    # Modo draws the box with flat faces, its material's smoothing angle being under a right angle. The plugin does not
    # read that angle from a Modo material, so the box is made flat here: the highlight is what is being compared.
    scene['meshes'] = [dict(mesh, smooth=mesh['name'] == 'Ball') for mesh in scene['meshes']]
    session = fixture.Session(FOLDER)
    session.runtime = runtime
    found = {}
    try:
        for case in report['cases']:
            if case.get('error'):
                print(case['name'], case['error'])
                continue
            theirs = modo_picture(runtime, case['name'])
            picture = drawn(session, dict(scene, materials=case['materials']))
            line = "%-22s now %.3f apart, %.3f of Modo's brightness" % (case['name'], apart(theirs, picture), sum(tiles(picture)) / max(sum(tiles(theirs)), 1e-9))
            if fit and case['look'] == 'gloss' and case['model'] != 'principled':
                best = None
                for beckmann in (False, True):
                    # Every tenth of roughness, then every fiftieth about the best of those.
                    tried = {}
                    def score(rough):
                        if rough not in tried:
                            picture = drawn(session, with_material(scene, case['materials'], roughness=rough, _beckmann=beckmann))
                            tried[rough] = (apart(theirs, picture, True), beckmann, rough, sum(tiles(picture)) / max(sum(tiles(theirs)), 1e-9))
                        return tried[rough]
                    coarse = min((score(step / 10.0) for step in range(1, 11)), key=lambda entry: entry[0])
                    fine = min((score(round(coarse[2] + step / 50.0, 2)) for step in range(-4, 5) if 0.02 <= coarse[2] + step / 50.0 <= 1.0), key=lambda entry: entry[0])
                    if best is None or fine[0] < best[0]:
                        best = fine
                # Then how strong: Modo's pictures hold light that has bounced from one thing to another, which a weaker
                # highlight dims at every bounce, so the strength that makes the picture as bright is searched for.
                low, high, strength = 0.0, 1.0, 1.0
                if best[3] > 1.0:
                    for _ in range(7):
                        strength = (low + high) / 2
                        picture = drawn(session, with_material(scene, case['materials'], roughness=best[2], _beckmann=best[1], _specular_strength=strength))
                        if sum(tiles(picture)) > sum(tiles(theirs)):
                            high = strength
                        else:
                            low = strength
                    strength = (low + high) / 2
                best = best + (strength,)
                found.setdefault(case['model'], []).append((case['roughness'], best))
                line += " | closest in shape: %s at roughness %.2f, %.3f apart once as bright, being %.3f of Modo's brightness; as bright at strength %.3f" % ('Beckmann' if best[1] else 'GGX', best[2], best[0], best[3], best[4])
            print(line, flush=True)
        if fit:
            (FOLDER / 'fit.json').write_text(json.dumps(found, indent=1))
    finally:
        session.process.kill()


if __name__ == '__main__':
    main()
