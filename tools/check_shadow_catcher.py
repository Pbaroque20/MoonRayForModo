"""Renders a shadow catcher with a MoonRay built with tools/port_shadow_catcher.py and checks it.

A ground of emission (0.2, 0.4, 0.6) set as a catcher, a red ball above it, a sun and a dim sky. The camera should see the
ground as its emission exactly where nothing shades it, darker in the ball's shadow, and the ball as it is. As a matte,
the ground shows no colour, alpha 0 where unshadowed and up to strength in the shadow. Each in scalar, vector and XPU.

    python tools/check_shadow_catcher.py <folder with moonray.exe> [runtime for the DSOs] [out folder]
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import native  # noqa: E402

EMISSION = (0.2, 0.4, 0.6)
SCENE = '''
local camera = PerspectiveCamera("camera") { ["node_xform"] = Mat4(1,0,0,0, 0,0.9701,-0.2425,0, 0,0.2425,0.9701,0, 0,2.5,7,1), ["focal"] = 30 }
local sun = DistantLight("sun") { ["node_xform"] = Mat4(0.8660,0,-0.5,0, -0.3536,0.7071,-0.6124,0, 0.3536,0.7071,0.6124,0, 0,0,0,1),
                                  ["intensity"] = 3, ["angular_extent"] = 3 }
local sky = EnvLight("sky") { ["intensity"] = 0.3 }
local lights = LightSet("lights") { sun, sky }
local ground = DwaBaseMaterial("ground") { ["albedo"] = Rgb(1,1,1), ["roughness"] = 1, ["specular"] = 0,
    ["emission"] = Rgb(%(emission)s), ["show_emission"] = true, ["modo_shadow_catcher"] = %(catcher)s, ["modo_shadow_strength"] = %(strength)s,
    ["modo_shadow_matte"] = %(matte)s }
local paint = DwaBaseMaterial("paint") { ["albedo"] = Rgb(0.8,0.1,0.1) }
local plane = RdlMeshGeometry("plane") { ["vertex_list_0"] = {Vec3(-10,0,-10), Vec3(10,0,-10), Vec3(10,0,10), Vec3(-10,0,10)},
    ["vertices_by_index"] = {0,3,2,1}, ["face_vertex_count"] = {4}, ["is_subd"] = false }
local ball = SphereGeometry("ball") { ["radius"] = 0.6, ["node_xform"] = Mat4(1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0.9,0,1) }
GeometrySet("geos") { plane, ball }
local layer = Layer("layer") { {plane, "", ground, lights}, {ball, "", paint, lights} }
RenderOutput("beauty") { ["result"] = 0, ["file_name"] = "%(image)s", ["channel_name"] = "beauty" }
RenderOutput("alpha") { ["result"] = 1, ["file_name"] = "%(image)s", ["channel_name"] = "A" }
SceneVariables { ["camera"] = camera, ["layer"] = layer, ["image_width"] = 320, ["image_height"] = 180, ["pixel_samples"] = 6,
    ["light_samples"] = 2, ["bsdf_samples"] = 2, ["max_depth"] = 3, ["sampling_mode"] = 0, ["two_stage_output"] = false }
'''
# Pixels: open ground far from the ball (left, near the bottom), the ball's shadow (behind it, away from the sun), the ball.
OPEN, SHADOW, BALL = (40, 160), None, (160, 75)


def render(exe, runtime, out, name, mode, catcher=True, strength=1.0, matte=False):
    scene, image = out / (name + '.rdla'), out / (name + '.exr')
    scene.write_text(SCENE % {'emission': ', '.join(map(str, EMISSION)), 'catcher': 'true' if catcher else 'false',
                              'strength': strength, 'matte': 'true' if matte else 'false', 'image': image.as_posix()}, encoding='utf-8')
    env = native.environment(runtime)
    env['PATH'] = str(Path(exe).parent) + ';' + env['PATH']
    done = subprocess.run([str(exe)] + native.arguments(scene, image, threads=8, mode=mode), env=env, capture_output=True,
                          text=True, timeout=600)
    (out / (name + '.log')).write_text(done.stdout + done.stderr, encoding='utf-8')
    if done.returncode or not image.is_file():
        raise SystemExit('%s failed (%d): %s' % (name, done.returncode, (done.stdout + done.stderr)[-1500:]))
    return image


def pixel(runtime, image, xy, channels='beauty.R,beauty.G,beauty.B,A'):
    tool = Path(runtime) / 'oiiotool.exe'
    done = subprocess.run([str(tool), str(image), '--ch', channels, '--cut', '5x5+%d+%d' % (xy[0] - 2, xy[1] - 2), '--printinfo:stats=1'],
                          env=native.environment(runtime), capture_output=True, text=True)
    line = next(l for l in done.stdout.splitlines() if 'Stats Avg' in l)
    return [float(v) for v in line.split(':')[1].split('(')[0].split()]


def darkest(runtime, image, region):
    """The darkest 5x5 patch of the ground in a region (x0, y0, x1, y1): the shadow."""
    best = None
    for y in range(region[1], region[3], 5):
        for x in range(region[0], region[2], 5):
            value = pixel(runtime, image, (x, y))
            if best is None or sum(value[:3]) < sum(best[1][:3]):
                best = ((x, y), value)
    return best


def main():
    exe = Path(sys.argv[1]) / 'moonray.exe'
    runtime = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / 'runtime/release-0.5.5.1'
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / 'test-results/shadow-catcher'
    out.mkdir(parents=True, exist_ok=True)
    report = []
    for mode in ('scalar', 'vector', 'xpu'):
        image = render(exe, runtime, out, 'catch-' + mode, mode)
        open_ground = pixel(runtime, image, OPEN)
        where, shade = darkest(runtime, image, (150, 95, 260, 150))
        ball = pixel(runtime, image, BALL)
        matte = render(exe, runtime, out, 'matte-' + mode, mode, matte=True)
        matte_open, matte_shade = pixel(runtime, matte, OPEN), pixel(runtime, matte, where)
        plain = render(exe, runtime, out, 'plain-' + mode, mode, catcher=False)
        report.append('%s: open ground %s (emission %s), shadow %s at %s, ball %s | matte open %s shadow %s | not a catcher %s'
                      % (mode, ['%.3f' % v for v in open_ground], EMISSION, ['%.3f' % v for v in shade], where,
                         ['%.3f' % v for v in ball], ['%.3f' % v for v in matte_open], ['%.3f' % v for v in matte_shade],
                         ['%.3f' % v for v in pixel(runtime, plain, OPEN)]))
        print(report[-1], flush=True)
        ok = (all(abs(a - b) < 0.03 for a, b in zip(open_ground, EMISSION)) and sum(shade[:3]) < 0.7 * sum(EMISSION)
              and matte_open[3] < 0.03 and matte_shade[3] > 0.3 and max(matte_open[:3]) < 0.02)
        print('  ', 'OK' if ok else 'NOT AS EXPECTED')
    (out / 'report.txt').write_text('\n'.join(report) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
