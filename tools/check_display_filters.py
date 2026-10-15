"""Render one scene with a MoonRay display filter over its beauty and say whether the filtered picture came out right.

A comparison scene (from tools/compare_moonlightipr.py) is rendered small with a ColorCorrectDisplayFilter that takes
the colour out of the beauty and doubles it (one stop up). Both the beauty and the filtered picture are written to one
EXR; the filtered one should be the beauty's brightness, twice over, in grey.

check_display_filters.py <runtime folder> [mode]"""
import pathlib
import struct
import subprocess
import sys

root = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import native

FILTER = '''
RenderOutput("/check/beauty") {
  ["file_name"] = "%(exr)s",
  ["channel_name"] = "beauty",
  ["result"] = 0,
}
ColorCorrectDisplayFilter("/check/grey") {
  ["input"] = RenderOutput("/check/beauty"),
  ["saturation"] = 0,
  ["exposure"] = 1,
}
RenderOutput("/check/filtered") {
  ["file_name"] = "%(exr)s",
  ["channel_name"] = "filtered",
  ["result"] = 15,
  ["display_filter"] = ColorCorrectDisplayFilter("/check/grey"),
}
'''


def pixels(runtime, exr, channels, pfm):
    subprocess.run([str(runtime / 'oiiotool.exe'), str(exr), '--ch', channels, '-d', 'float', '-o', str(pfm)],
                   env=native.environment(runtime), creationflags=0x08000000, check=True)
    data = pfm.read_bytes()
    header = data.split(b'\n', 3)
    width, height = map(int, header[1].split())
    return struct.unpack(('<' if float(header[2]) < 0 else '>') + '%df' % (width * height * 3), header[3])


def main():
    runtime = pathlib.Path(sys.argv[1]).resolve()
    mode = sys.argv[2] if len(sys.argv) > 2 else 'xpu'
    out = root / 'test-results/display-filters'
    out.mkdir(parents=True, exist_ok=True)
    scene, target, exr = out / ('%s.rdla' % mode), out / ('%s_main.exr' % mode), out / ('%s_filtered.exr' % mode)
    for old in (target, exr):
        if old.is_file():
            old.unlink()
    text = (root / 'build/moonlightipr/compare/dwa_skin.rdla').read_text(encoding='utf-8')
    scene.write_text(text + FILTER % {'exr': exr.as_posix()}, encoding='utf-8')
    done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(scene, target, 0, mode), env=native.environment(runtime),
                          cwd=str(out), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=0x08000000)
    log = done.stdout.decode(errors='replace')
    if done.returncode or not exr.is_file():
        print('FAILED (%d)\n%s' % (done.returncode, log[-1500:]))
        return 1
    beauty = pixels(runtime, exr, 'beauty.R,beauty.G,beauty.B', out / 'beauty.pfm')
    filtered = pixels(runtime, exr, 'filtered.R,filtered.G,filtered.B', out / 'filtered.pfm')
    worst, colour = 0.0, 0.0
    for i in range(0, len(beauty), 3):
        r, g, b = beauty[i:i + 3]
        grey = 2 * (0.2126 * r + 0.7152 * g + 0.0722 * b)
        fr, fg, fb = filtered[i:i + 3]
        worst = max(worst, abs(fr - grey) / max(grey, 1e-3))
        colour = max(colour, abs(fr - fg), abs(fg - fb))
    mean_b = sum(beauty) / len(beauty)
    mean_f = sum(filtered) / len(filtered)
    print('%s: beauty mean %.4f, filtered mean %.4f; largest colour left %.2e; largest gap from twice the brightness %.2f%%'
          % (mode, mean_b, mean_f, colour, worst * 100))
    return 0


if __name__ == '__main__':
    sys.exit(main())
