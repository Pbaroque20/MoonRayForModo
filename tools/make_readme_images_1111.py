"""README pictures for the 2026-11-11 round, from the checks' own renders (run those first):
- docs/images/moonlightipr-fireflies-dragon.jpg: the tester's refractive dragon in MoonLightIPR, Clamp From Bounce 1
  (MoonRay's) left and 0 (MoonLightIPR's own, now its default) right, Sample Clamp 10 in both
  (test-results/fireflies/scene.pickle, rendered here at 960 x 540, 1024 samples a pixel);
- docs/images/moonlightipr-aovs.jpg: the same dragon's AOVs from the MoonLightIPR session: beauty, diffuse, glossy,
  albedo; shading normal, world position, camera depth, shadow matte;
- docs/images/roughness-clamp-engines.jpg: rough gold balls among near-mirror metal, Roughness Clamp off (top) and 1
  (bottom), MoonRay left and MoonLightIPR right (test-results/moonlightipr-roughness-clamp, mirrors case).
make_readme_images_1111.py <runtime folder> [aovs|roughness_clamp|dragon|rect_light]..."""
import array
import pathlib
import pickle
import struct
import subprocess
import sys
import zlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
from moonray_modo import native

runtime = native.find_runtime(sys.argv[1])
env = native.environment(runtime)
tool = str(runtime / 'oiiotool.exe')
images = ROOT / 'docs/images'
work = ROOT / 'test-results/readme-1111'
work.mkdir(parents=True, exist_ok=True)


def pfm(path):
    data = path.read_bytes().split(b'\n', 3)
    width, height = map(int, data[1].split())
    values = array.array('f')
    values.frombytes(data[3][:width * height * 12])
    return width, height, values


def from_exr(path, size):
    """An EXR's R, G, B at size, as a PFM's numbers."""
    target = work / (path.stem + '.pfm')
    subprocess.run([tool, str(path), '--ch', 'R,G,B', '--resize', '%dx%d' % size, '-d', 'float', '-o', str(target)], env=env,
                   capture_output=True, check=True)
    return pfm(target)


def srgb(v):
    v = min(1.0, max(0.0, v))
    return round(255 * (12.92 * v if v <= .0031308 else 1.055 * v ** (1 / 2.4) - .055))


def grid(tiles, columns, gap=4):
    """Tiles (width, height, rows of 8-bit RGB bytes, top first) of one size in a grid, a gap of white between."""
    width, height = tiles[0][0], tiles[0][1]
    rows = (len(tiles) + columns - 1) // columns
    total_w, total_h = columns * width + (columns - 1) * gap, rows * height + (rows - 1) * gap
    blank = bytes([255, 255, 255])
    out = []
    for r in range(rows):
        for y in range(height):
            line = b''
            for c in range(columns):
                index = r * columns + c
                line += tiles[index][2][y] if index < len(tiles) else blank * width
                if c < columns - 1:
                    line += blank * gap
            out.append(line)
        if r < rows - 1:
            out += [blank * total_w] * gap
    return total_w, total_h, out


def tile(width, height, values, shown=lambda r, g, b: (r, g, b)):
    """A linear picture (PFM order, bottom row first) as 8-bit sRGB rows, top first, through shown()."""
    rows = []
    for y in reversed(range(height)):
        line = bytearray()
        for x in range(width):
            i = (y * width + x) * 3
            line += bytes(srgb(v) for v in shown(values[i], values[i + 1], values[i + 2]))
        rows.append(bytes(line))
    return width, height, rows


def save(picture, name, quality=90):
    width, height, rows = picture
    chunk = lambda kind, data: struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    png = work / (pathlib.Path(name).stem + '.png')
    png.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
                    + chunk(b'IDAT', zlib.compress(b''.join(b'\x00' + row for row in rows), 9)) + chunk(b'IEND', b''))
    target = images / name
    subprocess.run([tool, str(png), '--quality', str(quality), '-o', str(target)], env=env, capture_output=True, check=True)
    print('wrote', target, '%dx%d' % (width, height), '%d KB' % (target.stat().st_size // 1024))


def dragon():
    import compare_moonlightipr as compare
    W, H = 960, 540
    compare.WIDTH, compare.HEIGHT = W, H
    compare.fixture.WIDTH, compare.fixture.HEIGHT = W, H
    compare.MOONLIGHTIPR_SAMPLES = 1024
    compare.os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
    base = pickle.loads((ROOT / 'test-results/fireflies/scene.pickle').read_bytes())
    session = compare.fixture.Session(work)
    session.runtime = runtime
    tiles = []
    try:
        for depth in (1, 0):
            scene = dict(base, _flat_out=True, _moonlightipr_clamp_depth=depth)
            values = compare.moonlightipr(scene, session, 'dragon_depth%d' % depth)[0]
            tiles.append(tile(W, H, values))
    finally:
        if session.process.poll() is None:
            session.process.kill()
    save(grid(tiles, 2), 'moonlightipr-fireflies-dragon.jpg')


def aovs():
    """The dragon's AOVs from the MoonLightIPR session, every one gathered with the beauty: rendered once, then each asked
    for and sent at once, at 960 x 540, shown at half size."""
    import time
    import check_moonlightipr_session as fixture
    from moonray_modo import moonlightipr_scene
    W, H = 960, 540
    scene = dict(pickle.loads((ROOT / 'test-results/fireflies/scene.pickle').read_bytes()), _flat_out=True)
    session = fixture.Session(work)
    pictures = {}

    def until(done):
        for raw in session.process.stdout:
            line = raw.decode('utf-8', errors='replace').strip()
            if line.startswith('@@MODO_SHARED '):
                _, key, width, height, pixels = fixture.receive(line, session.process.pid)
                pictures['last'] = (width, height, pixels)
            if done(line):
                return
        raise RuntimeError('MoonLightIPR session ended early')

    def ask(text):
        session.process.stdin.write((text + '\n').encode())
        session.process.stdin.flush()

    # Shown as a compositor reads them: normals and positions as colours about grey, depth near to far as white to black
    # (squared, so that sRGB shows it as an even ramp).
    shown = [('beauty', 0, None), ('diffuse', 1, None), ('glossy', 2, None), ('albedo', 5, None),
             ('normal', 7, lambda r, g, b: (.5 + .5 * r, .5 + .5 * g, .5 + .5 * b)),
             ('position', 8, lambda r, g, b: tuple(min(1.0, max(0.0, .5 + .15 * v)) ** 2.2 for v in (r, g, b))),
             ('depth', 6, 'depth'), ('shadow', 11, None)]
    tiles = []
    try:
        ask('view 0 beauty')
        payload, _, _ = moonlightipr_scene.pack(scene, W, H, environment=0, known=set(), samples=1024)
        path = work / 'aovs.mls'
        path.write_bytes(payload)
        ask('scene 1 %s' % path)
        until(lambda line: line.startswith('@@MODO_SESSION DONE') or line.startswith('@@MODO_SESSION FAILED'))
        for name, number, mapping in shown:
            if number:
                ask('aov %d %s' % (number, name))
                until(lambda line: line.startswith('@@MODO_SHARED '))
            width, height, pixels = pictures['last']
            values = array.array('f')
            values.frombytes(bytes(pixels)[:width * height * 12])
            # Half size: each 2 x 2 block's mean.
            w, h = width // 2, height // 2
            half = array.array('f', [0.0]) * (w * h * 3)
            for y in range(h):
                for x in range(w):
                    for c in range(3):
                        half[(y * w + x) * 3 + c] = sum(values[((2 * y + dy) * width + 2 * x + dx) * 3 + c] for dy in (0, 1) for dx in (0, 1)) / 4
            if mapping == 'depth':
                seen = sorted(half[i * 3] for i in range(w * h) if half[i * 3] > 0)
                near, far = seen[len(seen) // 50], seen[len(seen) * 49 // 50]
                mapping = lambda r, g, b, near=near, far=far: (min(1.0, max(0.0, (far - r) / (far - near))) ** 2.2,) * 3 if r > 0 else (0, 0, 0)
            # The session's frames run bottom row first, as a PFM's do.
            tiles.append(tile(w, h, half, mapping) if mapping else tile(w, h, half))
    finally:
        ask('quit')
        time.sleep(1)
        if session.process.poll() is None:
            session.process.kill()
    save(grid(tiles, 4), 'moonlightipr-aovs.jpg')


def roughness_clamp():
    folder = ROOT / 'test-results/moonlightipr-roughness-clamp'
    tiles = []
    for factor in ('0', '1'):
        for engine in ('moonray', 'moonlightipr'):
            w, h, values = pfm(folder / ('mirrors_clamp%s_%s.pfm' % (factor, engine)))
            tiles.append(tile(w, h, values))
    save(grid(tiles, 2), 'roughness-clamp-engines.jpg')


def rect_light():
    """An area light (left) and the MoonRay RectLight Convert to MoonRay Rect Light made of it (right), both rendered by
    MoonRay: tools/probe_cl_light_convert.py's captures before and after."""
    import compare_moonlightipr as compare
    W, H = 640, 360
    compare.WIDTH, compare.HEIGHT = W, H
    compare.fixture.WIDTH, compare.fixture.HEIGHT = W, H
    compare.os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
    folder = ROOT / 'test-results/light-convert'
    pictures = []
    for index in (0, 1):
        scene = pickle.loads((folder / ('scene_%d.pickle' % index)).read_bytes())
        pictures.append(compare.moonray(scene, runtime, work, 'rect_light_%d' % index))
    off = [abs(a - b) for a, b in zip(*pictures)]
    print('area light against the RectLight: mean difference %.5f, largest %.4f' % (sum(off) / len(off), max(off)))
    save(grid([tile(W, H, values) for values in pictures], 2), 'convert-rect-light.jpg')


if __name__ == '__main__':
    for made in sys.argv[2:] or ('aovs', 'roughness_clamp', 'dragon'):
        globals()[made]()
