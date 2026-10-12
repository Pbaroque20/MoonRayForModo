"""The compositor's graphs run for real: each kind of node through the runtime's image tool, on a small made-up render,
and the picture that comes out measured against what the node should make of it.

check_compositor.py <runtime>"""
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import compositor, native

W, H = 64, 32


def write(path, pixel):
    """A float picture: PFM rows run from the bottom up."""
    with open(path, 'wb') as stream:
        stream.write(('PF\n%d %d\n-1.0\n' % (W, H)).encode('ascii'))
        for y in range(H):
            for x in range(W):
                stream.write(struct.pack('<3f', *pixel(x / (W - 1), y / (H - 1))))


def read(runtime, path, folder):
    target = folder / (Path(path).stem + '-read.pfm')
    subprocess.run([str(runtime / 'oiiotool.exe'), str(path), '--ch', '0,1,2', '-d', 'float', '-o', str(target)],
                   env=native.environment(runtime), check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    data = target.read_bytes()
    parts = data.split(b'\n', 3)
    assert parts[1].split() == [str(W).encode(), str(H).encode()], parts[1]
    values = struct.unpack(('<' if float(parts[2]) < 0 else '>') + '%df' % (W * H * 3), parts[3][:W * H * 12])
    return [values[i:i + 3] for i in range(0, len(values), 3)]


def run(runtime, graph, files, folder):
    steps, result = compositor.jobs(graph, files, {key: key for key in files}, folder)
    for args, target in steps:
        done = subprocess.run([str(runtime / 'oiiotool.exe')] + args, env=native.environment(runtime), stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        if done.returncode or not Path(target).is_file():
            raise RuntimeError('The image tool failed on %s: %s' % (' '.join(args), done.stdout.decode(errors='replace')[-400:]))
    return read(runtime, result, folder)


def graph(*nodes, **wires):
    """nodes are (identity, type, parameters, inputs); the last is wired to the output."""
    built = {identity: {'type': kind, 'parameters': held, 'inputs': inputs} for identity, kind, held, inputs in nodes}
    built['out'] = {'type': 'output', 'parameters': {}, 'inputs': {'image': nodes[-1][0]}}
    return {'nodes': built, 'root': 'out'}


def main():
    runtime = native.find_runtime(sys.argv[1])
    failures = []
    with tempfile.TemporaryDirectory(prefix='MoonRayCompositor-') as held:
        folder = Path(held)
        files = {'beauty': folder / 'beauty.pfm', 'second': folder / 'second.pfm', 'matte': folder / 'matte.pfm'}
        beauty = lambda u, v: (.2 + .6 * u, .4, .1 + .5 * v)
        second = lambda u, v: (.5, .25 + .5 * v, .75)
        matte = lambda u, v: (1.0, 1.0, 1.0) if u > .5 else (0.0, 0.0, 0.0)
        write(files['beauty'], beauty); write(files['second'], second); write(files['matte'], matte)
        a = ('a', 'input', {'buffer': 'beauty'}, {})
        b = ('b', 'input', {'buffer': 'second'}, {})
        m = ('m', 'input', {'buffer': 'matte'}, {})
        at = lambda picture, x, y: picture[y * W + x]

        def expect(name, built, wanted, tolerance=2e-3, places=((5, 5), (40, 20), (60, 3))):
            folder_of = folder / name
            folder_of.mkdir()
            try:
                picture = run(runtime, built, files, folder_of)
            except Exception as exc:
                failures.append('%s: %s' % (name, str(exc)[:300]))
                print('%-28s FAILED to run' % name)
                return
            worst = 0.0
            for x, y in places:
                u, v = x / (W - 1), y / (H - 1)
                worst = max(worst, max(abs(p - q) for p, q in zip(at(picture, x, y), wanted(u, v))))
            print('%-28s %s  (furthest %.4f)' % (name, 'ok' if worst <= tolerance else 'WRONG', worst))
            if worst > tolerance:
                failures.append('%s: %.4f from what it should be' % (name, worst))

        both = lambda f: (lambda u, v: tuple(f(p, q) for p, q in zip(beauty(u, v), second(u, v))))
        expect('the beauty as it is', graph(a), beauty)
        for mode, f in (('normal', lambda p, q: q), ('add', lambda p, q: p + q), ('multiply', lambda p, q: p * q),
                        ('screen', lambda p, q: 1 - (1 - p) * (1 - q)), ('lighten', max), ('darken', min),
                        ('difference', lambda p, q: abs(p - q))):
            expect('merge ' + mode, graph(a, b, ('x', 'merge', {'mode': mode, 'mix': 1.0}, {'a': 'a', 'b': 'b'})), both(f))
        expect('merge add at half', graph(a, b, ('x', 'merge', {'mode': 'add', 'mix': .5}, {'a': 'a', 'b': 'b'})), both(lambda p, q: p + .5 * q))
        expect('merge normal by a mask', graph(a, b, m, ('x', 'merge', {'mode': 'normal', 'mix': 1.0}, {'a': 'a', 'b': 'b', 'mask': 'm'})),
               lambda u, v: second(u, v) if u > .5 else beauty(u, v))
        expect('merge with nothing over', graph(a, ('x', 'merge', {'mode': 'add', 'mix': 1.0}, {'a': 'a'})), beauty)
        expect('grade exposure and tint', graph(a, ('g', 'grade', {'exposure': 1.0, 'tint': [1.0, .5, .25]}, {'image': 'a'})),
               lambda u, v: tuple(2 * p * t for p, t in zip(beauty(u, v), (1.0, .5, .25))))
        expect('grade gamma', graph(a, ('g', 'grade', {'gamma': 2.0}, {'image': 'a'})), lambda u, v: tuple(p ** .5 for p in beauty(u, v)))

        def grey(u, v):
            r, g, b_ = beauty(u, v)
            luma = .2126 * r + .7152 * g + .0722 * b_
            return (luma, luma, luma)
        expect('grade to no saturation', graph(a, ('g', 'grade', {'saturation': 0.0}, {'image': 'a'})), grey, tolerance=2e-2)
        # A blur and a glow of an even picture leave it as it was, away from its edges; the glow adds what is over the threshold.
        flat = folder / 'flat.pfm'
        write(flat, lambda u, v: (.5, .5, .5))
        files['flat'] = flat
        f = ('f', 'input', {'buffer': 'flat'}, {})
        expect('blur of an even picture', graph(f, ('x', 'blur', {'radius': 3.0}, {'image': 'f'})), lambda u, v: (.5, .5, .5), places=((32, 16),))
        expect('glow of an even picture', graph(f, ('x', 'glow', {'threshold': .25, 'radius': 3.0, 'strength': 2.0}, {'image': 'f'})),
               lambda u, v: (1.0, 1.0, 1.0), places=((32, 16),))
        expect('glow under its threshold', graph(f, ('x', 'glow', {'threshold': 1.0, 'radius': 3.0, 'strength': 2.0}, {'image': 'f'})),
               lambda u, v: (.5, .5, .5), places=((32, 16),))
        expect('nothing wired to the output', {'nodes': {'out': {'type': 'output', 'parameters': {}, 'inputs': {}}}, 'root': 'out'}, lambda u, v: (0, 0, 0))
    if failures:
        print('\n'.join(['', 'Compositor check FAILED:'] + failures))
        return 1
    print('Compositor check passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
