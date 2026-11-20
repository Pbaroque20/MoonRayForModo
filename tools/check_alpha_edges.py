"""How a render's soft edges are written with alpha: a lit quad, turned so its edges are antialiased, rendered by MoonRay
through the plugin's scene writer, once with no environment (black behind it) and once with an even grey environment
seen behind it. For each, the OpenEXR as MoonRay wrote it, the OpenEXR as the kit saves it (image_formats.
take_out_environment, with the switch on) and a 32-bit TIFF converted with its alpha (image_formats.convert) are read at
the edge pixels, binned by alpha.

Premultiplied (the OpenEXR convention, which After Effects and Nuke assume): colour is the surface's times alpha, and
goes to 0 with alpha. Straight (PNG; TIFF with unassociated alpha): colour is the surface's own whatever the alpha.
"Halo" is what an edge pixel holds beyond the surface's share, which a premultiplied reading lays over the background.
Usage: check_alpha_edges.py <runtime> [out folder]"""
import os
import shutil
import struct
import subprocess
import sys
import types
from pathlib import Path

root = Path(__file__).resolve().parents[1]
for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import image_formats, native, rdla  # noqa: E402

SURFACE = [.9, .5, .2]
TURN = 0.5236  # 30 degrees about the view, so the quad's edges cross the pixels slantwise


def turned(angle):
    import math
    c, s = math.cos(angle), math.sin(angle)
    return [c, s, 0, 0, -s, c, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def scene(background):
    value = {'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 4, 1], 'focal_mm': 35, 'film_mm': 36},
             'materials': {'': {'color': SURFACE, 'roughness': 1.0}},
             'meshes': [{'name': 'Quad', 'identity': 'quad', 'vertices': [[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]],
                         'faces': [[0, 1, 2, 3]], 'matrix': turned(TURN)}],
             'lights': [{'identity': 'key', 'name': 'Key', 'kind': 'DistantLight', 'color': [1, 1, 1], 'intensity': 2.0,
                         'matrix': rdla.IDENTITY}],
             'environments': [], 'aovs': ['alpha'], 'render_settings': {'sampling_mode': 0}}
    if background is not None:
        value['environments'] = [{'kind': 'constant', 'zenith': background, 'intensity': 1.0}]
    return value


def channels(runtime, source, names, folder, tag):
    """The named channels of a file, as rows of floats (PFM holds three: a single channel is read three times)."""
    target = folder / ('%s.pfm' % tag)
    picked = ','.join(names if len(names) == 3 else [names[0]] * 3)
    subprocess.run([str(runtime / 'oiiotool.exe'), '--no-autopremult', str(source), '--ch', picked, '-d', 'float', '-o', str(target)],
                   env=native.environment(runtime), check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    data = target.read_bytes()
    parts = data.split(b'\n', 3)
    width, height = (int(v) for v in parts[1].split())
    values = struct.unpack(('<' if float(parts[2]) < 0 else '>') + '%df' % (width * height * 3), parts[3][:width * height * 12])
    return [values[i * 3:i * 3 + 3] for i in range(width * height)]


def names(runtime, source):
    from moonray_modo.composite_output import channel_names
    return channel_names(runtime, source)


def binned(colour, alpha, surface):
    """For edge pixels by alpha: (alpha bin, pixels, mean red, mean red over alpha, mean halo in red)."""
    rows = []
    for low, high in ((.02, .2), (.2, .4), (.4, .6), (.6, .8), (.8, .98)):
        held = [(c[0], a[0]) for c, a in zip(colour, alpha) if low <= a[0] < high]
        if not held:
            continue
        red = sum(c for c, _ in held) / len(held)
        ratio = sum(c / a for c, a in held) / len(held)
        halo = sum(c - surface * a for c, a in held) / len(held)
        rows.append(('%.2f-%.2f' % (low, high), len(held), red, ratio, halo))
    return rows


def main():
    runtime = native.find_runtime(Path(sys.argv[1]))
    os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
    folder = Path(sys.argv[2]) if len(sys.argv) > 2 else root / 'test-results/alpha-edges'
    folder.mkdir(parents=True, exist_ok=True)
    for label, background in (('black', None), ('grey', [.5, .5, .5])):
        output = folder / (label + '.exr')
        source = folder / (label + '.rdla')
        source.write_text(rdla.scene_text(scene(background), 160, 120, 4, 0.0, str(output)), encoding='utf-8')
        subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(source, output, 0, 'vectorized'), env=native.environment(runtime),
                       cwd=str(folder), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
        held = names(runtime, output)
        colour = channels(runtime, output, ['R', 'G', 'B'], folder, label + '-rgb')
        alpha = channels(runtime, output, ['A'], folder, label + '-a')
        # The surface's own red: the mean of the pixels it covers whole.
        whole = [c[0] for c, a in zip(colour, alpha) if a[0] > .999]
        surface = sum(whole) / len(whole)
        print('== %s background: channels %s' % (label, ','.join(held)))
        print('   surface red where alpha is 1: %.4f; red where alpha is 0: %.4f' % (surface, max(c[0] for c, a in zip(colour, alpha) if a[0] < 1e-4)))
        print('   OpenEXR as MoonRay wrote it (premultiplied would give red/alpha = %.3f and halo 0):' % surface)
        for row in binned(colour, alpha, surface):
            print('     alpha %s: %4d px, red %.4f, red/alpha %.4f, halo %+.4f' % row)
        # As the kit saves it (render.py, image_formats.take_out_environment), where the switch is on.
        kept = folder / (label + '-saved.exr')
        shutil.copyfile(output, kept)
        changed = image_formats.take_out_environment(runtime, kept)
        colour = channels(runtime, kept, ['R', 'G', 'B'], folder, label + '-saved-rgb')
        alpha = channels(runtime, kept, ['A'], folder, label + '-saved-a')
        print('   OpenEXR as the kit saves it (%s; channels %s):' % ('environment taken out' if changed else 'left as it was', ','.join(names(runtime, kept))))
        for row in binned(colour, alpha, surface):
            print('     alpha %s: %4d px, red %.4f, red/alpha %.4f, halo %+.4f' % row)
        tif = image_formats.convert(runtime, 'tif32', output, folder / (label + '.tif'), alpha=True, background=output)
        straight = channels(runtime, tif, ['R', 'G', 'B'], folder, label + '-tif-rgb')
        cover = channels(runtime, tif, ['A'], folder, label + '-tif-a')
        print('   TIFF 32 with alpha (straight would give red = %.3f at every alpha):' % surface)
        for low, count, red, ratio, halo in binned(straight, cover, surface):
            print('     alpha %s: %4d px, red %.4f' % (low, count, red))


if __name__ == '__main__':
    main()
