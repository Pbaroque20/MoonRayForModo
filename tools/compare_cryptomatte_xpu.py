"""Cryptomatte from MoonRay Vector, MoonRay XPU and XPU2 compared, outside Modo: one small scene of the kit's (rdla.scene_text)
with the Objects and Materials Cryptomatte ticked, rendered to an EXR by each, and the EXRs read back as Nuke's keyer and
the kit's picker (cryptomatte_pick) read them: the layers' names, the manifests, every ID found and each ID's coverage.

compare_cryptomatte_xpu.py --runtime <MoonRay runtime> --xpu2 <runtime-xpu2> --output <empty folder> [--samples 8]
                           [--engines vector,xpu,xpu2-cpu,xpu2-gpu,xpu2,xpu-preview,xpu2-preview] [--size 320x200]

The -preview engines are the preview window's Render: the kit's session (MoonRay kept loaded in XPU mode, or XPU2's)
driven as the kit drives it (xpu2/interactive/session_harness.py), each buffer written to a file of its own.

Writes <output>/<engine>.exr and .log, <engine>-beauty.png, <engine>-crypto_object.png and -crypto_material.png (each
pixel's IDs in false colour, weighted by their coverage), and comparison.json: per engine against MoonRay Vector, whether
the layers and manifests are the same, the share of pixels whose IDs (rank 0) agree, the IDs found, and the mean and
largest difference in any ID's coverage. Exit 1 where an engine wrote no Cryptomatte or one with IDs MoonRay has not."""
import argparse
import json
import math
import re
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import cryptomatte, native, outputs, rdla  # noqa: E402

CATEGORIES = ('object', 'material')


def cube(identity, name, material, centre, size, turn=0.0):
    """A cube's eight corners and six faces, turned about the vertical by turn (radians)."""
    cx, cy, cz = centre
    c, s = math.cos(turn), math.sin(turn)
    vertices = []
    for x in (-1, 1):
        for y in (-1, 1):
            for z in (-1, 1):
                px, pz = x * size, z * size
                vertices.append([cx + px * c - pz * s, cy + y * size, cz + px * s + pz * c])
    faces = [[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]]
    return {'identity': identity, 'name': name, 'material': material, 'vertices': vertices, 'faces': faces, 'matrix': rdla.IDENTITY}


def fixture():
    meshes = [cube('cube_left', 'Cube Left', 'red', (-1.05, 0.0, 0.0), 0.45, 0.5),
              cube('cube_middle', 'Cube Middle', 'blue', (0.0, 0.15, -0.6), 0.55, 0.9),
              cube('cube_right', 'Cube Right', 'red', (1.0, -0.1, 0.3), 0.4, 0.25),
              {'identity': 'floor', 'name': 'Floor', 'material': 'grey', 'faces': [[0, 1, 2, 3]], 'matrix': rdla.IDENTITY,
               'vertices': [[-4, -0.5, -4], [-4, -0.5, 4], [4, -0.5, 4], [4, -0.5, -4]]}]
    # Looking down at the cubes: rows are the camera's axes (its Z behind it), pitched down by a quarter of a radian.
    c, s = math.cos(0.25), math.sin(0.25)
    camera = [1, 0, 0, 0, 0, c, -s, 0, 0, s, c, 0, 0, 1.1, 4.4, 1]
    return {'camera': {'matrix': camera, 'film_mm': 36, 'focal_mm': 40}, 'meshes': meshes,
            'materials': {'red': {'name': 'Red paint', 'color': [0.8, 0.12, 0.1]}, 'blue': {'name': 'Blue plastic', 'color': [0.1, 0.2, 0.8]},
                          'grey': {'name': 'Floor grey', 'color': [0.45, 0.45, 0.45]}},
            'lights': [], '_crypto_categories': True, 'render_settings': {'sampling_mode': 0},
            'custom_aovs': [{'name': 'crypto_' + c, 'kind': 'cryptomatte', 'category': c, 'depth': 6} for c in CATEGORIES]}


def bits(value):
    return struct.unpack('<I', struct.pack('<f', value))[0]


def read(path):
    """{part name: {'channels', 'manifest', 'layer', 'pixels': [{id: coverage}], 'width', 'height'}} of every Cryptomatte part,
    and the beauty as [(r, g, b, a)] from the first part."""
    import OpenImageIO as oiio
    found, beauty = {}, None
    inp = oiio.ImageInput.open(str(path))
    if not inp:
        raise ValueError('cannot open ' + str(path) + ': ' + oiio.geterror())
    parts = 0
    while inp.seek_subimage(parts, 0):
        parts += 1
    inp.close()
    for part in range(parts):
        image = oiio.ImageBuf(str(path), part, 0)
        spec = image.spec()
        names = list(spec.channelnames)
        if part == 0 and all(c in names for c in ('R', 'G', 'B')):
            index = [names.index(c) for c in ('R', 'G', 'B')] + ([names.index('A')] if 'A' in names else [])
            beauty = [tuple(px[i] for i in index) + ((1.0,) if len(index) == 3 else ()) for px in
                      (image.getpixel(x, y) for y in range(spec.height) for x in range(spec.width))]
        layers = sorted({n.split('.')[0][:-2] for n in names if re.fullmatch(r'[A-Za-z]+[0-9]{2}\.[RGBA]', n) and n.startswith('Crypto')})
        layers = [l for l in layers if l in ('Cryptomatte', 'CryptoObject', 'CryptoMaterial', 'CryptoAsset')]
        for layer in layers:
            pairs = [(names.index(n), names.index(n[:-1] + ('G' if n.endswith('R') else 'A'))) for n in names
                     if re.fullmatch(layer + r'[0-9]{2}\.[RB]', n)]
            prefix = 'cryptomatte/' + ('%08x' % cryptomatte.hash32(layer))[:7] + '/'
            manifest = json.loads(spec.get_string_attribute(prefix + 'manifest') or '{}')
            header = {k: spec.get_string_attribute(prefix + k) for k in ('name', 'hash', 'conversion')}
            pixels = []
            for y in range(spec.height):
                for x in range(spec.width):
                    v = image.getpixel(x, y)
                    pixel = {}
                    for i, w in pairs:
                        if v[w] > 0 and bits(v[i]):
                            pixel[bits(v[i])] = pixel.get(bits(v[i]), 0.0) + v[w]
                    pixels.append(pixel)
            key = spec.get_string_attribute('name') or ('part%d' % part)
            found[key + '/' + layer] = {'channels': sorted(n for n in names if n.startswith(layer)), 'manifest': manifest,
                                       'header': header, 'pixels': pixels, 'width': spec.width, 'height': spec.height,
                                       'category': spec.get_string_attribute('MoonRayForModo/cryptomatteCategory')}
    return found, beauty


def colour(identity):
    """A matte's false colour, from its ID's bits (as Nuke's keyer shows them)."""
    h = cryptomatte.hash32(str(identity))
    return ((h & 255) / 255.0, ((h >> 8) & 255) / 255.0, ((h >> 16) & 255) / 255.0)


def write_png(path, width, height, rgb):
    import OpenImageIO as oiio
    spec = oiio.ImageSpec(width, height, 3, oiio.UINT8)
    out = oiio.ImageOutput.create(str(path))
    flat = []
    for r, g, b in rgb:
        flat += [max(0, min(255, int(round(c * 255)))) for c in (r, g, b)]
    out.open(str(path), spec)
    out.write_image(bytes(flat))
    out.close()


def srgb(c):
    c = max(0.0, c)
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def pictures(folder, engine, width, height, crypto, beauty):
    """<engine>-beauty.png (sRGB) and <engine>-<output>.png: each pixel's mattes in their false colours, by coverage."""
    if beauty:
        write_png(folder / (engine + '-beauty.png'), width, height, [tuple(srgb(c) for c in px[:3]) for px in beauty])
    for key, layer in crypto.items():
        rgb = []
        for pixel in layer['pixels']:
            c = [0.0, 0.0, 0.0]
            for identity, weight in pixel.items():
                for i, v in enumerate(colour(identity)):
                    c[i] += v * weight
            rgb.append(tuple(c))
        write_png(folder / ('%s-%s.png' % (engine, key.split('/')[0])), layer['width'], layer['height'], rgb)


def compare(reference, other):
    """Rank-0 ID agreement and coverage differences of one Cryptomatte against MoonRay's."""
    same = total = 0
    differences = []
    for p, q in zip(reference['pixels'], other['pixels']):
        if not p and not q:
            continue
        total += 1
        top_p = max(p, key=p.get) if p else None
        top_q = max(q, key=q.get) if q else None
        same += top_p == top_q
        for k in set(p) | set(q):
            differences.append(abs(p.get(k, 0.0) - q.get(k, 0.0)))
    ids_ref = set().union(*reference['pixels'])
    ids_other = set().union(*other['pixels'])
    return {'pixels_with_mattes': total, 'rank0_id_match_percent': round(100.0 * same / max(1, total), 3),
            'ids_reference': len(ids_ref), 'ids_found': len(ids_other), 'ids_identical': ids_ref == ids_other,
            'ids_not_in_reference': ['%08x' % i for i in sorted(ids_other - ids_ref)],
            'manifest_identical': reference['manifest'] == other['manifest'], 'header_identical': reference['header'] == other['header'],
            'channels_identical': reference['channels'] == other['channels'],
            'coverage_mean_abs_difference': round(sum(differences) / max(1, len(differences)), 5),
            'coverage_max_abs_difference': round(max(differences, default=0.0), 5)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--xpu2', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=8, help="MoonRay's pixel samples (a side: 8 is 64 a pixel); XPU2 the same")
    parser.add_argument('--size', default='320x200')
    parser.add_argument('--engines', default='vector,xpu,xpu2-cpu,xpu2-gpu,xpu2,xpu-preview,xpu2-preview')
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args()
    width, height = (int(v) for v in args.size.split('x'))
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    runtime, xpu2 = args.runtime.resolve(), args.xpu2.resolve()
    env = native.environment(runtime)
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    report = {'scene': 'four meshes (three cubes, a floor), three materials; Objects and Materials Cryptomatte, depth 6',
              'size': [width, height], 'samples': args.samples, 'engines': {}}
    engines = args.engines.split(',')
    for engine in engines:
        image = folder / (engine + '.exr')
        source = folder / (engine + '.rdla')
        scene = fixture()
        scene['_xpu2'] = engine.startswith('xpu2')
        if scene['_xpu2']:
            # XPU2's sampling generations as a render to files has them (scene_settings), spending exactly the samples
            # asked for with no noise target: every pixel the same samples on each device, so that the processor's and
            # the cards' renders can be compared bit for bit.
            from moonray_modo.scene_settings import DEFAULTS
            scene['xpu2_generations'] = dict(DEFAULTS['xpu2_generations'], samples=0, spend='samples', noise=0.0)
        preview = engine.endswith('-preview')
        if preview:
            # The preview window's Render: the kit's session (MoonRay kept loaded, or XPU2's), each buffer to a file of
            # its own (outputs.preview), the Cryptomatte's among them, read back as the window reads them.
            files = {key: str(folder / ('%s.%s.exr' % (engine, key))) for key in outputs.preview(scene)}
            for path in files.values():
                if Path(path).exists():
                    Path(path).unlink()
            scene['preview_buffer_files'] = files
            source.write_text(rdla.scene_text(scene, width, height, args.samples, 1.0, None), encoding='utf-8')
            work = folder / (engine + '-session')
            if work.exists():
                import shutil
                shutil.rmtree(work)
            exe = runtime / 'moonray.exe' if engine == 'xpu-preview' else xpu2 / 'moonray_xpu2.exe'
            extra = (['--env', 'MOONRAY_XPU2_MOONRAY=' + str(runtime / 'moonray.exe'), '--env', 'PATH=%s;%s;%s' % (xpu2, runtime, env['PATH'])]
                     if engine != 'xpu-preview' else ['--env', 'PATH=' + env['PATH'], '--env', 'RDL2_DSO_PATH=' + env['RDL2_DSO_PATH']])
            for key in ('MOONRAY_MODO_CRYPTO_ONCE', 'MOONRAY_MODO_CRYPTO_VOLUMES', 'MOONRAY_MODO_OPAQUE_ALPHA', 'MOONRAY_MODO_CAMERA_LIGHT_LPE'):
                extra += ['--env', '%s=%s' % (key, env[key])]
            command = [sys.executable, str(ROOT / 'xpu2/interactive/session_harness.py'), '--exe', str(exe), '--scene', str(source),
                       '--output', str(work), '--mode', 'xpu', '--timeout', str(args.timeout)] + extra
            start = time.time()
            with (folder / (engine + '.log')).open('w', encoding='utf-8') as log:
                done = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, creationflags=flags, timeout=args.timeout + 60)
            text = (work / 'protocol.log').read_text(encoding='utf-8', errors='replace') if (work / 'protocol.log').is_file() else ''
            entry = {'exit_code': done.returncode, 'seconds': round(time.time() - start, 2), 'status': native.execution_status(text),
                     'fell_back_to_moonray': '@@MODO_XPU2 FALLBACK' in text, 'preview_files': sorted(k for k, p in files.items() if Path(p).is_file())}
            report['engines'][engine] = entry
            crypto = {}
            for category in CATEGORIES:
                path = Path(files.get('crypto_' + category, ''))
                if path.is_file():
                    layer = next(iter(read(path)[0].values()), None)
                    if layer:
                        crypto['crypto_%s/Cryptomatte' % category] = layer
            beauty = read(Path(files['beauty']))[1] if Path(files['beauty']).is_file() else None
            entry['cryptomatte_parts'] = sorted(crypto)
            entry['_crypto'], entry['_beauty'] = crypto, beauty
            pictures(folder, engine, width, height, crypto, beauty)
            continue
        source.write_text(rdla.scene_text(scene, width, height, args.samples, 1.0, str(image)), encoding='utf-8')
        if engine in ('vector', 'xpu'):
            command = [str(runtime / 'moonray.exe')] + native.arguments(source, image, 0, 'vectorized' if engine == 'vector' else 'xpu')
            run_env = env
        else:
            mode = {'xpu2-cpu': '0', 'xpu2-gpu': '1', 'xpu2': '2'}[engine]
            command = [str(xpu2 / 'moonray_xpu2.exe'), 'render', '-in', str(source), '--mode', mode]
            run_env = dict(env, MOONRAY_XPU2_MOONRAY=str(runtime / 'moonray.exe'), PATH=str(xpu2) + ';' + env['PATH'])
            run_env.pop('RDL2_DSO_PATH', None)
            run_env.pop('REZ_MOONRAY_ROOT', None)
        if image.exists():
            image.unlink()
        start = time.time()
        with (folder / (engine + '.log')).open('w', encoding='utf-8') as log:
            done = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=run_env, creationflags=flags, timeout=args.timeout)
        text = (folder / (engine + '.log')).read_text(encoding='utf-8', errors='replace')
        entry = {'exit_code': done.returncode, 'seconds': round(time.time() - start, 2), 'status': native.execution_status(text),
                 'fell_back_to_moonray': 'MoonRay renders the scene instead' in text or '@@MODO_XPU2 FALLBACK' in text}
        report['engines'][engine] = entry
        if not image.is_file():
            entry['error'] = 'no EXR written'
            continue
        crypto, beauty = read(image)
        entry['cryptomatte_parts'] = sorted(crypto)
        entry['_crypto'], entry['_beauty'] = crypto, beauty
        pictures(folder, engine, width, height, crypto, beauty)
    held ={engine: (entry.pop('_crypto', None), entry.pop('_beauty', None)) for engine, entry in report['engines'].items()}
    reference, ref_beauty = held.get('vector', (None, None))
    failed = False
    for engine, entry in report['engines'].items():
        crypto, beauty = held[engine]
        if not crypto:
            failed = True
            entry['cryptomatte'] = 'none written'
            continue
        if reference is not None:
            entry['against_vector'] = {}
            for key in sorted(set(reference) | set(crypto)):
                if key not in crypto or key not in reference:
                    entry['against_vector'][key] = 'missing in ' + ('this render' if key not in crypto else 'MoonRay Vector')
                    failed = True
                    continue
                result = compare(reference[key], crypto[key])
                entry['against_vector'][key] = result
                # A preview's buffer file has no header: the window gives it its manifest as it saves it (cryptomatte.header).
                failed |= bool(result['ids_not_in_reference']) or not (result['manifest_identical'] or engine.endswith('-preview'))
        if beauty and ref_beauty and engine != 'vector':
            diffs = [abs(a - b) for p, q in zip(ref_beauty, beauty) for a, b in zip(p[:3], q[:3])]
            entry['beauty_mean_abs_difference_against_vector'] = round(sum(diffs) / max(1, len(diffs)), 5)
    # XPU2's rule: the processor and the cards render the same picture, bit for bit; its Cryptomatte too.
    cpu, gpu = held.get('xpu2-cpu', (None, None)), held.get('xpu2-gpu', (None, None))
    if cpu[0] and gpu[0]:
        exact = {key: sum(p == q for p, q in zip(cpu[0][key]['pixels'], gpu[0][key]['pixels'])) * 100.0 / len(cpu[0][key]['pixels'])
                 for key in cpu[0] if key in gpu[0]}
        report['xpu2_cpu_vs_gpu'] = {'cryptomatte_pixels_bit_identical_percent': exact,
                                     'beauty_pixels_bit_identical_percent': sum(p == q for p, q in zip(cpu[1], gpu[1])) * 100.0 / max(1, len(cpu[1]))}
    (folder / 'comparison.json').write_text(json.dumps(report, indent=1), encoding='utf-8')
    print(json.dumps(report, indent=1))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
