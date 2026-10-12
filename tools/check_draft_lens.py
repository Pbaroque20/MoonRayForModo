"""A draft's outlines lie where the picture's own edges are, under each kind of camera.

For the comparison's ordinary, fisheye and spherical camera scenes MoonLightIPR draws the draft and renders the
picture. Where the picture's brightness steps sharply from one pixel to the next there is an edge; the share of the
draft's line pixels that have such an edge within two pixels says whether the lines are through the same lens.

check_draft_lens.py <runtime>"""
import copy
import os
import sys

import compare_moonlightipr as compare
from moonray_modo import native
import check_moonlightipr_session as fixture

SCENES = ['entity_textured_light', 'fisheye_camera', 'fisheye_equidistant', 'spherical_camera']
W, H = compare.WIDTH, compare.HEIGHT


def luminance(values):
    return [.2126 * values[i] + .7152 * values[i + 1] + .0722 * values[i + 2] for i in range(0, len(values), 3)]


def main():
    runtime = native.find_runtime(sys.argv[1])
    folder = fixture.BUILD / 'compare'
    os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
    scenes = compare.scenes(folder)
    session = fixture.Session(folder)
    session.runtime = runtime
    worst = 1.0
    try:
        for name in [n for n in SCENES if n in scenes]:
            compare.MOONLIGHTIPR_SAMPLES = 64
            picture = luminance(compare.moonlightipr(copy.deepcopy(scenes[name]), session, name + '_lens_picture')[0])
            lines = luminance(compare.moonlightipr(dict(copy.deepcopy(scenes[name]), _draft=2), session, name + '_lens_draft')[0])
            # The picture's edges: a step of a quarter or more of the brighter of two neighbours.
            edge = bytearray(W * H)
            for y in range(H - 1):
                for x in range(W - 1):
                    i = y * W + x
                    a = picture[i]
                    for b in (picture[i + 1], picture[i + W]):
                        if abs(a - b) > .25 * max(a, b, .02):
                            edge[i] = 1
            drawn = on = 0
            for y in range(3, H - 3):
                for x in range(3, W - 3):
                    if lines[y * W + x] > .5:
                        drawn += 1
                        on += any(edge[(y + dy) * W + x + dx] for dy in (-2, -1, 0, 1, 2) for dx in (-2, -1, 0, 1, 2))
            share = on / drawn if drawn else 0.0
            worst = min(worst, share)
            print('%-24s %6d line pixels, %3.0f%% of them on an edge of the picture' % (name, drawn, 100 * share), flush=True)
        session.process.stdin.write(b'quit\n')
        session.process.stdin.flush()
        session.process.wait(timeout=10)
    finally:
        if session.process.poll() is None:
            session.process.kill()
    return worst


if __name__ == '__main__':
    main()
