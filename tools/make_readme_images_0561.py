"""The front page's pictures for 0.5.6.1, rendered by MoonRay (build/native-renderer-avx/bin or a runtime):

- docs/images/glass-alpha.png: glass, thin glass, frosted glass, a half-present ball and a solid one against the sky,
  each laid over a checkerboard by its own alpha (premultiplied, the Environment background taken out): before (glass
  as opaque as paint, Glass in alpha off) and now.
- docs/images/shadow-catcher.png: a ball over a plain ground lit by the sun, the ground as a shadow catcher (the camera
  sees its colour darkened only by the shadows), and as a matte laid over a checkerboard (its alpha the shadows alone).

    python tools/make_readme_images_0561.py [folder with moonray.exe] [runtime for the DSOs]
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import native  # noqa: E402
import check_material_alpha  # noqa: E402
import check_shadow_catcher  # noqa: E402

IMAGES = ROOT / 'docs/images'


def tool(runtime, *args):
    done = subprocess.run([str(Path(runtime) / 'oiiotool.exe')] + [str(a) for a in args], env=native.environment(runtime),
                          capture_output=True, text=True)
    if done.returncode:
        raise SystemExit(done.stdout + done.stderr)


def render(exe, runtime, scene, image, mode='vector', env=None):
    environment = native.environment(runtime)
    environment['PATH'] = str(Path(exe).parent) + ';' + environment['PATH']
    environment.update(env or {})
    done = subprocess.run([str(exe)] + native.arguments(scene, image, threads=8, mode=mode), env=environment, capture_output=True,
                          text=True, timeout=900)
    if done.returncode:
        raise SystemExit((done.stdout + done.stderr)[-1500:])


def over_checker(runtime, image, target, size, beauty='beauty', background=None):
    """The render laid over a checkerboard by its alpha: its colour less the Environment background (premultiplied), then
    shown in sRGB."""
    width, height = size
    colour = [image, '--ch', '%s.R,%s.G,%s.B' % (beauty, beauty, beauty), '--chnames', 'R,G,B']
    if background:
        colour += [image, '--ch', '%s.R,%s.G,%s.B' % (background, background, background), '--chnames', 'R,G,B', '--sub', '--clamp:min=0']
    tool(runtime, '--pattern', 'checker:width=16:height=16:color1=0.35,0.35,0.35:color2=0.6,0.6,0.6', '%dx%d' % size, '3', '--chnames', 'R,G,B', '--ch', 'R,G,B,A=1.0',
         *colour, image, '--ch', 'A', '--chappend', '--chnames', 'R,G,B,A', '--swap', '--over',
         '--ch', 'R,G,B', '--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o', target)


def label(runtime, source, words, target):
    tool(runtime, source, '--text:x=10:y=22:size=18:color=1,1,1', words, '-o', target)


def main():
    exe = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / 'build/native-renderer-avx/bin') / 'moonray.exe'
    runtime = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / 'runtime/release-0.5.5.1'
    IMAGES.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        work = Path(folder)
        # Glass: before and now.
        pictures = []
        for name, switch in (('before', '0'), ('now', '1')):
            image = work / ('glass-%s.exr' % name)
            scene = work / ('glass-%s.rdla' % name)
            scene.write_text(check_material_alpha.scene_text(image.as_posix()).replace('["pixel_samples"] = 6', '["pixel_samples"] = 16'),
                             encoding='utf-8')
            render(exe, runtime, scene, image, env={'MOONRAY_MODO_GLASS_ALPHA': switch})
            shown = work / ('glass-%s.png' % name)
            over_checker(runtime, image, shown, (480, 120), background='environment_background')
            pictures.append(shown)
        tool(runtime, pictures[0], pictures[1], '--mosaic:pad=6', '1x2', '-o', IMAGES / 'glass-alpha.png')
        # The shadow catcher: plain ground, catcher, matte over a checkerboard.
        pictures = []
        for name, catcher, matte in (('plain', False, False), ('catcher', True, False), ('matte', True, True)):
            image = work / ('catch-%s.exr' % name)
            scene = work / ('catch-%s.rdla' % name)
            text = check_shadow_catcher.SCENE.replace('["pixel_samples"] = 6', '["pixel_samples"] = 16')
            # The sky seen behind, and the plain ground a matt surface of the photo's colour, without the emission a
            # catcher shows.
            if not matte:
                text = text.replace('EnvLight("sky") { ["intensity"] = 0.3 }', 'EnvLight("sky") { ["intensity"] = 0.3, ["visible_in_camera"] = 1 }')
            if not catcher:
                text = text.replace('["albedo"] = Rgb(1,1,1), ["roughness"] = 1', '["albedo"] = Rgb(%(emission)s), ["roughness"] = 1')
                text = text.replace('["show_emission"] = true', '["show_emission"] = false')
            scene.write_text(text % {
                'emission': ', '.join(map(str, check_shadow_catcher.EMISSION)), 'catcher': 'true' if catcher else 'false',
                'strength': 1.0, 'matte': 'true' if matte else 'false', 'image': image.as_posix()}, encoding='utf-8')
            render(exe, runtime, scene, image)
            shown = work / ('catch-%s.png' % name)
            if matte:
                over_checker(runtime, image, shown, (320, 180))
            else:
                tool(runtime, image, '--ch', 'beauty.R,beauty.G,beauty.B', '--chnames', 'R,G,B', '--colorconvert', 'linear', 'sRGB',
                     '-d', 'uint8', '-o', shown)
            pictures.append(shown)
        tool(runtime, *pictures, '--mosaic:pad=6', '3x1', '-o', IMAGES / 'shadow-catcher.png')
    print('wrote', IMAGES / 'glass-alpha.png', 'and', IMAGES / 'shadow-catcher.png')


if __name__ == '__main__':
    main()
