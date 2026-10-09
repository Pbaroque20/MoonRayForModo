"""What the RDL importer makes of a scene, and how the result renders against the original.

Usage: check_rdl_import.py <moonray-runtime> <scene.rdla> [...]
           what each scene holds, what the importer would make of it and what it says it leaves out
       check_rdl_import.py <moonray-runtime> --documents <folder> <scene.rdla> [...]
           also keep each scene as MoonRay's reader gave it, for tools/probe_rdl_import.py to import inside Modo
       check_rdl_import.py <moonray-runtime> --compare <folder>
           render each original and the scene Modo wrote back after importing it, and say how alike the pictures are
MoonRay's own reader opens each scene in a separate process, as the import dialog does."""
import collections
import json
import struct
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import native, rdl_import

MARKER = b'@@MODO_RDL_JSON'
TILE = 20


def document(runtime, path):
    """The scene as MoonRay's reader sees it: every object with its class and attributes."""
    together = rdl_import.files(path)
    done = subprocess.run([str(runtime / 'modo_rdl_import.exe'), together[0], str(runtime)] + together[1:], env=native.environment(runtime), cwd=str(path.parent),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    offset = done.stdout.rfind(MARKER)
    if done.returncode or offset < 0:
        raise RuntimeError(done.stderr.decode(errors='replace')[-1500:] or 'The reader returned nothing')
    return json.loads(done.stdout[offset + len(MARKER):].decode('utf-8'))


def rendered(runtime, scene, output, size, cwd):
    """Render a scene file at a size and return its pixels' luminance, row by row."""
    scenes = [word for name in rdl_import.files(scene) for word in ('-in', name)]
    for args in ([str(runtime / 'moonray.exe')] + scenes + ['-out', str(output), '-size', str(size[0]), str(size[1]), '-exec_mode', 'auto'],
                 [str(runtime / 'oiiotool.exe'), str(output), '--ch', 'R,G,B', '-d', 'float', '-o', str(output.with_suffix('.pfm'))],
                 [str(runtime / 'oiiotool.exe'), str(output), '--ch', 'R,G,B', '--colorconvert', 'linear', 'sRGB', '-o', str(output.with_suffix('.png'))]):
        done = subprocess.run(args, env=native.environment(runtime), cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        if done.returncode:
            raise RuntimeError(done.stdout.decode(errors='replace')[-1500:])
    data = output.with_suffix('.pfm').read_bytes()
    header = data.split(b'\n', 3)
    width, height = (int(v) for v in header[1].split())
    values = struct.unpack(('<' if float(header[2]) < 0 else '>') + '%df' % (width * height * 3), header[3])
    return width, height, [.2126 * values[i] + .7152 * values[i + 1] + .0722 * values[i + 2] for i in range(0, len(values), 3)]


def tiles(width, height, pixels):
    columns, rows = width // TILE, height // TILE
    sums = [0.0] * (columns * rows)
    for y in range(rows * TILE):
        for x in range(columns * TILE):
            sums[(y // TILE) * columns + x // TILE] += pixels[y * width + x]
    return [value / (TILE * TILE) for value in sums]


def compare(runtime, folder):
    report = json.loads((folder / 'report.json').read_text())
    for name, entry in sorted(report.items()):
        if not isinstance(entry, dict):
            continue
        if 'error' in entry:
            print('%-26s failed inside Modo: %s' % (name, entry['error'].strip().splitlines()[-1]))
            continue
        source = Path(json.loads((folder / (name + '.document.json')).read_text(encoding='utf-8'))['_path'])
        try:
            a = rendered(runtime, source, folder / (name + '.original.exr'), entry['size'], source.parent)
            b = rendered(runtime, folder / (name + '.imported.rdla'), folder / (name + '.imported.exr'), entry['size'], folder)
        except RuntimeError as exc:
            print('%-26s could not be rendered: %s' % (name, str(exc).strip().splitlines()[-1][:200]))
            continue
        before, after = tiles(*a), tiles(*b)
        pairs = [(x, y) for x, y in zip(before, after) if max(x, y) > 1e-3]
        close = sum(abs(x - y) <= .1 * max(x, y) for x, y in pairs)
        print('%-26s brightness %.3f of the original, %3d%% of the picture within 10%%   (%s)' % (
            name, sum(after) / max(sum(before), 1e-12), 100 * close / max(1, len(pairs)), entry.get('said', '')))
        for warning in entry.get('warnings', []):
            print('      Modo: ' + warning[:200])


def main():
    runtime = native.find_runtime(sys.argv[1])
    arguments = sys.argv[2:]
    if arguments[:1] == ['--compare']:
        return compare(runtime, Path(arguments[1]).resolve())
    keep = None
    if arguments[:1] == ['--documents']:
        keep = Path(arguments[1]).resolve()
        keep.mkdir(parents=True, exist_ok=True)
        arguments = arguments[2:]
    for name in arguments:
        path = Path(name).resolve()
        print(path.parent.name + '/' + path.name)
        try:
            read = document(runtime, path)
        except RuntimeError as exc:
            print('  could not be read:', str(exc).strip().splitlines()[-1])
            continue
        if keep:
            (keep / ((path.parent.name if path.stem == 'scene' else path.stem) + '.document.json')).write_text(json.dumps(dict(read, _path=str(path))), encoding='utf-8')
        kinds = collections.Counter(record['type'] for record in read['objects'])
        print('  holds: ' + ', '.join('%d %s' % (count, kind) for kind, count in sorted(kinds.items())))
        plan = rdl_import.plan(read, path)
        print('  makes: ' + rdl_import.summary(plan))
        for warning in plan['warnings']:
            print('  - ' + warning)


if __name__ == '__main__':
    main()
