"""The alpha of each kind of see-through material against the sky, in MoonRay's scalar, vector and XPU modes.

Balls in a row against a visible environment: solid paint, DwaBase glass (transmission 1), DwaBase thin-walled glass,
the kit's ModoGlassMaterial, presence 0.5, and DwaBase with transmission 0.5. Prints the alpha at each ball's middle.

    python tools/check_material_alpha.py <folder with moonray.exe> [runtime for the DSOs] [out folder] [modes]
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import native  # noqa: E402

BALLS = [
    ('solid', 'DwaBaseMaterial("solid") { ["albedo"] = Rgb(0.8,0.2,0.2) }'),
    ('glass', 'DwaBaseMaterial("glass") { ["transmission"] = 1, ["refractive_index"] = 1.5, ["roughness"] = 0 }'),
    ('thin glass', 'DwaBaseMaterial("thin") { ["transmission"] = 1, ["thin_geometry"] = true, ["roughness"] = 0 }'),
    ('frosted glass', 'DwaBaseMaterial("frosted") { ["transmission"] = 1, ["refractive_index"] = 1.5, ["roughness"] = 0.3 }'),
    ('presence 0.5', 'DwaBaseMaterial("half") { ["albedo"] = Rgb(0.2,0.8,0.2), ["presence"] = 0.5 }'),
    ('transmission 0.5', 'DwaBaseMaterial("milky") { ["albedo"] = Rgb(0.2,0.2,0.8), ["transmission"] = 0.5, ["refractive_index"] = 1.5 }'),
]


def scene_text(image, extra=''):
    lines = ['local camera = PerspectiveCamera("camera") { ["node_xform"] = Mat4(1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,14,1), ["focal"] = 30 }',
             'local sky = EnvLight("sky") { ["intensity"] = 1, ["visible_in_camera"] = 1, ["label"] = "modo_environment" }',
             'local lights = LightSet("lights") { sky }']
    entries = []
    for index, (name, material) in enumerate(BALLS):
        x = (index - (len(BALLS) - 1) / 2) * 1.6
        lines.append('local m%d = %s' % (index, material))
        lines.append('local b%d = SphereGeometry("ball%d") { ["radius"] = 0.7, ["node_xform"] = Mat4(1,0,0,0, 0,1,0,0, 0,0,1,0, %g,0,0,1) }'
                     % (index, index, x))
        entries.append('{b%d, "", m%d, lights}' % (index, index))
    lines.append('GeometrySet("geos") { %s }' % ', '.join('b%d' % i for i in range(len(BALLS))))
    lines.append('local layer = Layer("layer") { %s }' % ', '.join(entries))
    lines.append('RenderOutput("beauty") { ["result"] = 0, ["file_name"] = "%s", ["channel_name"] = "beauty" }' % image)
    lines.append('RenderOutput("alpha") { ["result"] = 1, ["file_name"] = "%s", ["channel_name"] = "A" }' % image)
    # The kit's Environment background with glass see-through (rdla.GLASS_SKY_LPE): the sky directly and through glass.
    lines.append('RenderOutput("environment_background") { ["result"] = 8, ["lpe"] = "C(<TS>|<TG>|<Ts>)*<L.\'modo_environment\'>", ["file_name"] = "%s", '
                 '["channel_name"] = "environment_background" }' % image)
    # And the Environment lighting beside it (rdla.GLASS_LIT_LPE): with only the sky lighting the scene, the two add up to
    # the beauty.
    lines.append('RenderOutput("environment_lighting") { ["result"] = 8, ["lpe"] = "C(<TS>|<TG>|<Ts>)*(<R.>|<TD>|<V.>).*<L.\'modo_environment\'>", '
                 '["file_name"] = "%s", ["channel_name"] = "environment_lighting" }' % image)
    lines.append('SceneVariables { ["camera"] = camera, ["layer"] = layer, ["image_width"] = 480, ["image_height"] = 120, '
                 '["pixel_samples"] = 6, ["max_depth"] = 8, ["max_mirror_depth"] = 8, ["sampling_mode"] = 0, ["two_stage_output"] = false %s}' % extra)
    return '\n'.join(lines) + '\n'


def alpha_at(runtime, image, x, y=60, channel='A'):
    tool = Path(runtime) / 'oiiotool.exe'
    done = subprocess.run([str(tool), str(image), '--ch', channel, '--cut', '5x5+%d+%d' % (x - 2, y - 2), '--printinfo:stats=1'],
                          env=native.environment(runtime), capture_output=True, text=True)
    return float(next(l for l in done.stdout.splitlines() if 'Stats Avg' in l).split(':')[1].split()[0])


def main():
    exe = Path(sys.argv[1]) / 'moonray.exe'
    runtime = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / 'runtime/release-0.5.5.1'
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else ROOT / 'test-results/material-alpha'
    modes = sys.argv[4].split(',') if len(sys.argv) > 4 else ['scalar', 'vector', 'xpu']
    out.mkdir(parents=True, exist_ok=True)
    env = native.environment(runtime)
    env['PATH'] = str(exe.parent) + ';' + env['PATH']
    for mode in modes:
        image = out / ('alpha-%s.exr' % mode)
        scene = out / ('alpha-%s.rdla' % mode)
        scene.write_text(scene_text(image.as_posix()), encoding='utf-8')
        done = subprocess.run([str(exe)] + native.arguments(scene, image, threads=8, mode=mode), env=env, capture_output=True,
                              text=True, timeout=600)
        if done.returncode:
            raise SystemExit((done.stdout + done.stderr)[-1500:])
        # Ball middles: 480 wide, a 30 mm lens on MoonRay's 24 mm film, 14 m away.
        values = []
        for index, (name, _) in enumerate(BALLS):
            x = 240 + (index - (len(BALLS) - 1) / 2) * 1.6 / 14 * 30 / 24 * 480
            at = int(round(x))
            beauty, sky = alpha_at(runtime, image, at, channel='beauty.G'), alpha_at(runtime, image, at, channel='environment_background.G')
            lit = alpha_at(runtime, image, at, channel='environment_lighting.G')
            values.append('%s %.3f (beauty G %.3f = sky %.3f + lit %.3f%s)' % (name, alpha_at(runtime, image, at), beauty, sky, lit,
                                                                            '' if abs(beauty - sky - lit) < 0.01 else ' DOES NOT ADD UP'))
        print(mode + ': ' + ', '.join(values), flush=True)


if __name__ == '__main__':
    main()
