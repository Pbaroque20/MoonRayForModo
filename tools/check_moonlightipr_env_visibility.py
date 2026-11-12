"""MoonLightIPR keeps an environment's visibility switches (Modo's Visible to Camera, Indirect Rays, Reflection Rays and
Refraction Rays, MoonRay's EnvLight visible_in_camera and visible_* lobes): four balls in a row, diffuse, mirror, rough
metal and glass, under a white environment and nothing else, rendered with each switch off in turn, then with two
environments, one lighting the scene and a red one only seen in reflections. Each ball's middle and the background are
measured; the check fails where a ball keeps light its rays should not see, or loses light they should.
Writes test-results/moonlightipr-env-visibility/<case>.pfm/.ppm and report.json."""
import json
import math
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
import check_moonlightipr_session as fixture  # noqa: E402

W, H = fixture.WIDTH, fixture.HEIGHT
folder = ROOT / 'test-results/moonlightipr-env-visibility'
folder.mkdir(parents=True, exist_ok=True)
CENTRES = {'diffuse': -2.55, 'mirror': -0.85, 'rough': 0.85, 'glass': 2.55}


def row(identity, color, roughness, metallic=0.0, **extra):
    return {**extra, 'name': identity, 'base_layer_id': identity, 'shader': 'DwaBaseMaterial', 'standard_material': True,
            'color': color, 'raw_color': color, 'diffuse_amount': 1.0, 'roughness': roughness, 'metallic': metallic,
            'specular': [.04] * 3, 'raw_specular': [1, 1, 1], 'specular_amount': .04, 'emission': [0, 0, 0],
            'raw_emission': [1, 1, 1], 'emission_amount': 0.0, 'ior': 1.5, 'layer_opacity': 1.0, 'layer_blend': 'normal',
            'material_groups': [], 'layers': []}


def scene(environments):
    vertices, faces = fixture.ball()
    return {
        'camera': {'matrix': fixture.look_at([0, 0, 10], [0, 0, 0]), 'focal_mm': 50.0, 'film_mm': 36.0},
        'materials': {'': {'material_stack': [row('diffuse', [.8, .8, .8], 1.0)]},
                      'mirror': {'material_stack': [row('mirror', [.9, .9, .9], 0.0, metallic=1.0)]},
                      'rough': {'material_stack': [row('rough', [.9, .9, .9], .35, metallic=1.0)]},
                      'glass': {'material_stack': [row('glass', [.8, .8, .8], 0.0, transmission=1.0, transmission_color=[1, 1, 1],
                                                       refraction_roughness=0.0)]}},
        'meshes': [{'name': name, 'identity': name, 'vertices': vertices, 'faces': faces, 'material': '' if name == 'diffuse' else name,
                    'matrix': fixture.placed(x, 0, 0, .7)} for name, x in CENTRES.items()],
        'lights': [],
        'environments': environments}


def white(**flags):
    return dict({'kind': 'constant', 'name': 'White', 'intensity': 1.0, 'zenith': [1, 1, 1], 'nadir': [1, 1, 1]}, **flags)


def measure(pixels):
    values = struct.unpack('<%df' % (W * H * 3), pixels)
    scale = W / (36.0 / 50.0 * 10.0)    # pixels a unit at the balls' distance

    def window(cx, cy, half):
        total = [0.0] * 3
        for y in range(cy - half, cy + half):
            for x in range(cx - half, cx + half):
                for c in range(3):
                    total[c] += values[(y * W + x) * 3 + c]
        return [round(v / (4 * half * half), 4) for v in total]
    result = {name: window(int(W / 2 + x * scale), H // 2, 12) for name, x in CENTRES.items()}
    result['background'] = window(W // 2, 40, 12)
    return result


CASES = [('all', [white()]),
         ('camera_off', [white(camera=False)]),
         ('indirect_off', [white(indirect=False)]),
         ('reflection_off', [white(reflection=False)]),
         ('refraction_off', [white(refraction=False)]),
         ('two_environments', [white(reflection=False, refraction=False, camera=False),
                               {'kind': 'constant', 'name': 'Red', 'intensity': 1.0, 'zenith': [1, 0, 0], 'nadir': [1, 0, 0],
                                'indirect': False}])]


def main():
    for stale in folder.glob('*.mls'):
        stale.unlink()
    session = fixture.Session(folder)
    report = {}
    try:
        for name, environments in CASES:
            result = session.submit(scene(environments))
            fixture.write_images(folder / name, result['pixels'])
            report[name] = measure(result['pixels'])
            report[name]['seconds'] = round(result['done_ms'] / 1000, 2)
            print('%-18s %s' % (name, report[name]))
    finally:
        session.process.kill()
    (folder / 'report.json').write_text(json.dumps(report, indent=1))

    grey = lambda v: sum(v) / 3
    base, problems = report['all'], []

    def expect(case, part, test, why):
        if not test(report[case][part]):
            problems.append('%s, %s %s: %s' % (case, part, report[case][part], why))
    for part in CENTRES:
        expect('camera_off', part, lambda v, p=part: abs(grey(v) - grey(base[p])) < .03, 'the camera switch changed a ball')
    expect('camera_off', 'background', lambda v: grey(v) < .001, 'the camera still sees the environment')
    expect('indirect_off', 'diffuse', lambda v: grey(v) < .12, 'diffuse light still sees the environment')
    for part in ('mirror', 'rough', 'glass', 'background'):
        expect('indirect_off', part, lambda v, p=part: abs(grey(v) - grey(base[p])) < .03, 'lost more than diffuse light')
    expect('reflection_off', 'mirror', lambda v: grey(v) < .02, 'the mirror still reflects the environment')
    expect('reflection_off', 'rough', lambda v: grey(v) < .05, 'the rough metal still reflects the environment')
    expect('reflection_off', 'diffuse', lambda v: grey(v) > grey(base['diffuse']) - .06, 'the diffuse ball lost more than its shine')
    expect('reflection_off', 'background', lambda v: abs(grey(v) - grey(base['background'])) < .01, 'the background changed')
    expect('refraction_off', 'glass', lambda v: grey(v) < .3 * grey(base['glass']), 'the glass still shows the environment through it')
    for part in ('diffuse', 'mirror', 'rough', 'background'):
        expect('refraction_off', part, lambda v, p=part: abs(grey(v) - grey(base[p])) < .03, 'changed with refractions off')
    expect('two_environments', 'mirror', lambda v: v[0] > .7 and v[1] < .02 and v[2] < .02, 'the mirror does not show the red one alone')
    expect('two_environments', 'rough', lambda v: v[0] > .5 and v[1] < .05, 'the rough metal does not show the red one alone')
    expect('two_environments', 'diffuse', lambda v: abs(v[0] - v[1]) < .08 and v[1] > .4, 'the diffuse ball is not lit white')
    # The red one is left visible to the camera and to refractions; the white one is hidden from both.
    expect('two_environments', 'background', lambda v: v[0] > .99 and v[1] < .001, 'the camera does not see the red one alone')
    expect('two_environments', 'glass', lambda v: v[0] > .8 and v[1] < .05, 'the glass does not show the red one through it')
    if problems:
        raise SystemExit('Environment visibility check failed:\n  ' + '\n  '.join(problems))
    print('MoonLightIPR environment visibility check passed')


if __name__ == '__main__':
    main()
