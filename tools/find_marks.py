"""Where a picture has pixels that stand out darkly from those around them, which is how a pixel caught part way
through a sample shows.

find_marks.py <picture.pfm> [...]   For each: how many pixels are under half (and under three quarters) of the middle
value of the eight pixels two away from them, in what part of the picture they lie, and the worst few. A mark in the
denoiser's guides or in the beauty shows here; one the denoiser has smeared out does not, being no longer sharp."""
import struct
import sys


def read(path):
    data = open(path, 'rb').read()
    parts = data.split(b'\n', 3)
    width, height = (int(v) for v in parts[1].split())
    values = struct.unpack(('<' if float(parts[2]) < 0 else '>') + '%df' % (width * height * 3), parts[3][:width * height * 12])
    return width, height, values


def marks(path):
    width, height, values = read(path)
    # Normals run from -1 to 1 and an albedo or a beauty from 0 up: the length of the three is what is compared.
    size = [(values[i] ** 2 + values[i + 1] ** 2 + values[i + 2] ** 2) ** .5 for i in range(0, len(values), 3)]
    ring = [(-2, -2), (0, -2), (2, -2), (-2, 0), (2, 0), (-2, 2), (0, 2), (2, 2)]
    half, quarter, worst, bright = [], 0, [], 0
    for y in range(2, height - 2):
        row = y * width
        for x in range(2, width - 2):
            # Too bright: over half as much again as the middle of the eight pixels touching it. Pixels caught the
            # other way lie on a sparse grid, every other one, so those touching one are sound.
            beside = sorted(size[row + dy * width // 2 + x + dx // 2] for dx, dy in ring)
            if beside[3] > .02 and size[row + x] > 1.5 * (beside[3] + beside[4]) / 2:
                bright += 1
            around = sorted(size[row + dy * width + x + dx] for dx, dy in ring)
            middle = (around[3] + around[4]) / 2
            # Only where what is around is even, which leaves out edges, and is not black.
            if middle < .02 or around[6] - around[1] > .15 * middle:
                continue
            value = size[row + x]
            if value < .75 * middle:
                quarter += 1
                if value < .5 * middle:
                    half.append((x, y))
                worst.append((value / middle, x, height - 1 - y))
    worst.sort()
    box = (min(x for x, _ in half), min(height - 1 - y for _, y in half), max(x for x, _ in half), max(height - 1 - y for _, y in half)) if half else None
    return width, height, len(half), quarter, box, worst[:5], bright


if __name__ == '__main__':
    for path in sys.argv[1:]:
        width, height, half, quarter, box, worst, bright = marks(path)
        print('%s (%d x %d): %d pixels under half of those around them, %d under three quarters, %d over half as bright again as those touching them; the dark lie within %s; darkest (share, x, y from the top): %s'
              % (path.replace('\\', '/').rsplit('/', 1)[-1], width, height, half, quarter, bright, box, [(round(s, 2), x, y) for s, x, y in worst]))
