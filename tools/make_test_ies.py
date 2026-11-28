"""Write IES (LM-63) photometric files for testing the kit's IES lights, made up here (no luminaire's data):

  down.ies     an axially symmetric downlight: one horizontal angle, 0 to 90 degrees, a beam of about 30 degrees.
  asym.ies     the lower half, horizontal angles 0 to 360 in steps of 30: brighter toward C0 than C180 and toward C90
               than C270, to read which way a renderer turns the C planes.
  up.ies       the upper half only (90 to 180 degrees), axially symmetric: which way is up.
  quad.ies     a quadrant (0 to 90 horizontal) symmetric file, wider along C0 than along C90.

make_test_ies.py <folder>"""
import math
import sys
from pathlib import Path


def write(path, vertical, horizontal, candela, lumens=-1, multiplier=1.0):
    lines = ['IESNA:LM-63-2002', '[TEST] made up for MoonRayForModo tests', '[MANUFAC] none', 'TILT=NONE',
             '1 %g %g %d %d 1 2 0.1 0.1 0' % (lumens, multiplier, len(vertical), len(horizontal)),
             '1.0 1.0 100']
    lines.append(' '.join('%g' % v for v in vertical))
    lines.append(' '.join('%g' % h for h in horizontal))
    for row in candela:
        lines.append(' '.join('%.3f' % c for c in row))
    Path(path).write_text('\n'.join(lines) + '\n')


def main():
    folder = Path(sys.argv[1])
    folder.mkdir(parents=True, exist_ok=True)
    lower = [5.0 * i for i in range(19)]
    # A beam: full to 20 degrees, down to nothing at 45.
    beam = [1000.0 if v <= 20 else 1000.0 * max(0.0, math.cos(math.radians((v - 20) / 25 * 90))) ** 2 if v < 45 else 0.0 for v in lower]
    write(folder / 'down.ies', lower, [0.0], [beam])
    horizontal = [30.0 * i for i in range(13)]
    wide = [1000.0 * math.cos(math.radians(v)) ** 0.5 if v < 80 else 0.0 for v in lower]
    write(folder / 'asym.ies', lower, horizontal,
          [[w * (1.0 + 0.6 * math.cos(math.radians(h)) + 0.3 * math.sin(math.radians(h))) for w in wide] for h in horizontal])
    whole = [5.0 * i for i in range(37)]
    write(folder / 'up.ies', whole, [0.0], [[0.0 if v < 100 else 800.0 * math.sin(math.radians(v - 90)) ** 0.5 for v in whole]])
    quadrant = [15.0 * i for i in range(7)]
    write(folder / 'quad.ies', lower, quadrant,
          [[1000.0 * max(0.0, math.cos(math.radians(v))) * (1.0 if v < 60 - 30 * math.sin(math.radians(h)) else 0.1) for v in lower]
           for h in quadrant])


if __name__ == '__main__':
    main()
