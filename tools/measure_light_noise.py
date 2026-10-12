"""How noisy MoonLightIPR's picture is under each kind of light, with a picture on the light and without.

For each of the comparison's textured-light scenes, and the same scene with the light's picture taken off, MoonLightIPR
renders at a few samples and at very many. The noise is the root mean square difference between the two, as a share
of the picture's mean brightness. No MoonRay render is made.

measure_light_noise.py <runtime> [samples] [reference samples]"""
import copy
import math
import os
import sys

import compare_moonlightipr as compare
from moonray_modo import native
import check_moonlightipr_session as fixture

SCENES = ['entity_textured_light', 'textured_disklight', 'textured_cylinderlight', 'textured_distantlight', 'textured_spherelight', 'textured_spotlight']


def luminance(values):
    return [.2126 * values[i] + .7152 * values[i + 1] + .0722 * values[i + 2] for i in range(0, len(values), 3)]


def render(scene, session, name, samples):
    compare.MOONLIGHTIPR_SAMPLES = samples
    return luminance(compare.moonlightipr(scene, session, name)[0])


def main():
    runtime = native.find_runtime(sys.argv[1])
    few = int(sys.argv[2]) if len(sys.argv) > 2 else 16
    many = int(sys.argv[3]) if len(sys.argv) > 3 else 4096
    # The comparison's own folder: its scenes' images and volume are made there once.
    folder = fixture.BUILD / 'compare'
    folder.mkdir(parents=True, exist_ok=True)
    os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
    scenes = compare.scenes(folder)
    harsh = None
    if os.environ.get('MOONRAY_NOISE_HARSH'):
        # A picture that is dark but for a small bright patch: where choosing by brightness tells most.
        harsh = folder / 'harsh.ppm'
        compare.write_ppm_file(harsh, 256, 256, lambda u, v: [1.0] * 3 if .55 < u < .8 and .3 < v < .55 else [.01] * 3)
    session = fixture.Session(folder)
    session.runtime = runtime
    try:
        print('%-26s %10s %10s   noise at %d samples, as a share of the mean brightness' % ('light', 'pictured', 'plain', few))
        for name in SCENES:
            row = []
            for pictured in (True, False):
                scene = copy.deepcopy(scenes[name])
                if pictured and harsh:
                    for entity in scene['entities']:
                        entity['parameters']['texture'] = str(harsh)
                if not pictured:
                    for entity in scene['entities']:
                        entity['parameters'].pop('texture', None)
                label = name + ('_harsh' if pictured and harsh else '' if pictured else '_plain')
                reference = render(scene, session, label + '_many', many)
                rough = render(scene, session, label + '_few', few)
                mean = sum(reference) / len(reference)
                row.append(math.sqrt(sum((a - b) ** 2 for a, b in zip(rough, reference)) / len(reference)) / mean if mean > 0 else float('nan'))
            print('%-26s %9.1f%% %9.1f%%' % (scenes[name]['entities'][0]['class'], 100 * row[0], 100 * row[1]), flush=True)
        session.process.stdin.write(b'quit\n')
        session.process.stdin.flush()
        session.process.wait(timeout=10)
    finally:
        if session.process.poll() is None:
            session.process.kill()


if __name__ == '__main__':
    main()
