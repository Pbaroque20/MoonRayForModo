"""Dense glitter in MoonRay's Vector and XPU modes (tools/port_flake_caches.py): a ball of fine, dense metallic flakes,
many to a pixel, which sends MoonRay to its stochastic flakes lobe. Before the fix, Vector and XPU ended with a stack
overflow (exit code 0xC00000FD) the first time it was shaded; Scalar rendered it.

Renders the ball in each mode with MOONRAY_MODO_FLAKE_CACHES on (and, with --off, Vector with it off), prints each
render's exit code, time and the ball's average colour, and fails unless every on render finished and Vector and XPU
are within 3% of Scalar.

    python tools/check_flake_caches.py <folder with moonray.exe> [runtime for the DSOs] [out folder] [--off]
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import native  # noqa: E402

GLITTER = ('DwaMetalMaterial("flakes") { ["metallic_color"] = Rgb(0.604, 0.357, 0.071), '
           '["metallic_edge_color"] = Rgb(1, 0.698, 0.396), ["show_glitter"] = true, ["glitter_space"] = 4, '
           '["glitter_size_A"] = 0.006, ["glitter_size_B"] = 0.006, ["glitter_density"] = 25 }')


def scene_text(image, samples=16):
    return '\n'.join([
        'local camera = PerspectiveCamera("camera") { ["node_xform"] = Mat4(1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,12,1), ["focal"] = 35 }',
        'local sky = EnvLight("sky") { ["intensity"] = 1, ["visible_in_camera"] = 0 }',
        'local key = SphereLight("key") { ["radius"] = 1, ["intensity"] = 20, '
        '["node_xform"] = Mat4(1,0,0,0, 0,1,0,0, 0,0,1,0, 4,5,8,1) }',
        'local lights = LightSet("lights") { sky, key }',
        'local flakes = ' + GLITTER,
        'local ball = SphereGeometry("ball") { ["radius"] = 1.5 }',
        'GeometrySet("geos") { ball }',
        'local layer = Layer("layer") { {ball, "", flakes, lights} }',
        'RenderOutput("beauty") { ["result"] = 0, ["file_name"] = "%s", ["channel_name"] = "beauty" }' % image,
        'SceneVariables { ["camera"] = camera, ["layer"] = layer, ["image_width"] = 160, ["image_height"] = 160, '
        '["pixel_samples"] = %d, ["sampling_mode"] = 0, ["two_stage_output"] = false }' % samples,
    ]) + '\n'


def average(runtime, image):
    """The ball's average colour: the middle 60x60 of the picture."""
    done = subprocess.run([str(Path(runtime) / 'oiiotool.exe'), str(image), '--cut', '60x60+50+50', '--printinfo:stats=1'],
                          env=native.environment(runtime), capture_output=True, text=True)
    line = next(l for l in done.stdout.splitlines() if 'Stats Avg' in l)
    return [float(v) for v in line.split(':')[1].split()[:3]]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    exe = Path(args[0]).resolve() / 'moonray.exe'
    runtime = Path(args[1]) if len(args) > 1 else ROOT / 'dist/personal-kit/Luxology/Kits/MoonRayForModo/runtime'
    out = Path(args[2]) if len(args) > 2 else ROOT / 'test-results/flake-caches'
    out.mkdir(parents=True, exist_ok=True)
    env = native.environment(runtime)
    env['PATH'] = str(exe.parent) + ';' + env['PATH']
    runs = [('scalar', '1'), ('vector', '1'), ('xpu', '1')] + ([('vector', '0')] if '--off' in sys.argv else [])
    colours, failed = {}, []
    for mode, switch in runs:
        name = 'flakes-%s-%s' % (mode, 'on' if switch == '1' else 'off')
        image, scene = out / (name + '.exr'), out / (name + '.rdla')
        scene.write_text(scene_text(image.as_posix()), encoding='utf-8')
        env['MOONRAY_MODO_FLAKE_CACHES'] = switch
        start = time.time()
        done = subprocess.run([str(exe)] + native.arguments(scene, image, threads=8, mode=mode), env=env, capture_output=True,
                              text=True, timeout=900)
        took = time.time() - start
        (out / (name + '.log')).write_text(done.stdout + done.stderr, encoding='utf-8')
        code = done.returncode & 0xFFFFFFFF
        if code:
            print('%s: exit code 0x%08X after %.1f s%s' % (name, code, took, ' (stack overflow)' if code == 0xC00000FD else ''),
                  flush=True)
            if switch == '1':
                failed.append(name)
            continue
        colours[name] = average(runtime, image)
        print('%s: %.1f s, ball average %s' % (name, took, ' '.join('%.4f' % c for c in colours[name])), flush=True)
    reference = colours.get('flakes-scalar-on')
    for name in ('flakes-vector-on', 'flakes-xpu-on'):
        if reference and name in colours:
            off = max(abs(a - b) / max(b, 1e-4) for a, b in zip(colours[name], reference))
            print('%s vs scalar: %.2f%% at most' % (name, off * 100), flush=True)
            if off > 0.03:
                failed.append(name + ' (colour)')
    if failed:
        raise SystemExit('failed: ' + ', '.join(failed))
    print('dense glitter renders in every mode')


if __name__ == '__main__':
    main()
