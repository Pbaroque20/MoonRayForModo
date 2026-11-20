"""Float images for MoonLightIPR written with their rows in order (pfm_files): oiiotool's own PFM writer turned over each
block of rows by itself, so any picture larger than one block (a 3840 x 2160 one, an 8K HDRI) came out with its bands
out of order, and a MoonLightIPR Render of a car under an 8K garage HDRI, which takes its environment at full size, was
lit from below. oiiotool writes an uncompressed float TIFF instead, turned into a PFM here."""
import array
import os
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import pfm_files  # noqa: E402

OIIOTOOL = ROOT / 'runtime/release-0.5.5.1/oiiotool.exe'


def tiff(path, rows, channels=3, rows_per_strip=2, order='<'):
    """An uncompressed float TIFF of these rows (top first, each a list of grey values), as oiiotool writes one: strips of
    rows, 32-bit float samples."""
    width, height = len(rows[0]), len(rows)
    pixels = [struct.pack(order + '%df' % (width * channels), *[v for value in row for v in [value] * channels]) for row in rows]
    strips = [b''.join(pixels[y:y + rows_per_strip]) for y in range(0, height, rows_per_strip)]
    head = 8
    entries = []
    extra = b''
    data_at = head + 2 + 12 * 12 + 4 + 64

    def entry(tag, kind, values):
        nonlocal extra
        code, size = {3: ('H', 2), 4: ('I', 4)}[kind]
        packed = struct.pack(order + code * len(values), *values)
        if len(packed) <= 4:
            entries.append(struct.pack(order + 'HHI', tag, kind, len(values)) + packed.ljust(4, b'\0'))
        else:
            where = data_at + len(extra)
            extra += packed
            entries.append(struct.pack(order + 'HHII', tag, kind, len(values), where))
    offsets_at = data_at + 4 * len(strips) * 2 + 2 * channels * 2
    offsets, at = [], offsets_at
    for strip in strips:
        offsets.append(at)
        at += len(strip)
    entry(256, 4, [width])
    entry(257, 4, [height])
    entry(258, 3, [32] * channels)
    entry(259, 3, [1])
    entry(262, 3, [2 if channels == 3 else 1])
    entry(273, 4, offsets)
    entry(274, 3, [1])
    entry(277, 3, [channels])
    entry(278, 3, [rows_per_strip])
    entry(279, 4, [len(s) for s in strips])
    entry(284, 3, [1])
    entry(339, 3, [3] * channels)
    directory = struct.pack(order + 'H', len(entries)) + b''.join(entries) + b'\0\0\0\0'
    body = directory.ljust(data_at - head, b'\0') + extra
    body = body.ljust(offsets_at - head, b'\0')
    marker = b'II' if order == '<' else b'MM'
    path.write_bytes(marker + struct.pack(order + 'HI', 42, head) + body + b''.join(strips))


def pfm_rows(path):
    """A PFM's rows as grey values (its first channel), top first."""
    data = path.read_bytes()
    parts = data.split(b'\n', 3)
    kind, (width, height), scale = parts[0], map(int, parts[1].split()), float(parts[2])
    channels = 3 if kind == b'PF' else 1
    values = array.array('f')
    values.frombytes(parts[3][:width * height * channels * 4])
    if (scale < 0) != (sys.byteorder == 'little'):
        values.byteswap()
    rows = [[values[(y * width + x) * channels] for x in range(width)] for y in range(height)]
    return kind, list(reversed(rows))


class TiffToPfm(unittest.TestCase):
    def test_rows_come_bottom_first_whatever_the_strips(self):
        rows = [[float(y)] * 3 for y in range(7)]
        with tempfile.TemporaryDirectory() as folder:
            source, target = pathlib.Path(folder) / 'a.tif', pathlib.Path(folder) / 'a.pfm'
            tiff(source, rows, rows_per_strip=3)
            pfm_files.tiff_to_pfm(source, target)
            kind, read = pfm_rows(target)
        self.assertEqual(kind, b'PF')
        self.assertEqual(read, rows)

    def test_one_channel_and_big_endian(self):
        rows = [[float(y) + 0.5] * 2 for y in range(4)]
        with tempfile.TemporaryDirectory() as folder:
            source, target = pathlib.Path(folder) / 'a.tif', pathlib.Path(folder) / 'a.pfm'
            tiff(source, rows, channels=1, order='>')
            pfm_files.tiff_to_pfm(source, target)
            kind, read = pfm_rows(target)
        self.assertEqual(kind, b'Pf')
        self.assertEqual(read, rows)

    def test_through_tiff_leaves_no_tiff_behind(self):
        rows = [[1.0, 2.0], [3.0, 4.0]]
        with tempfile.TemporaryDirectory() as folder:
            target = pathlib.Path(folder) / 'a.pfm'
            pfm_files.through_tiff(lambda path: tiff(path, rows), target)
            self.assertEqual(sorted(p.name for p in pathlib.Path(folder).iterdir()), ['a.pfm'])
            self.assertEqual(pfm_rows(target)[1], rows)


@unittest.skipUnless(OIIOTOOL.is_file(), 'needs the runtime oiiotool')
class OiiotoolRows(unittest.TestCase):
    """The runtime's oiiotool: a 3840 x 2160 gradient (1 at the top, 0 at the bottom), written as a PFM by oiiotool
    itself and through the TIFF. oiiotool's own came out with its halves swapped."""

    def test_a_large_picture_keeps_its_rows_in_order(self):
        from moonray_modo import native
        env = native.environment(OIIOTOOL.parent)
        with tempfile.TemporaryDirectory() as folder:
            source, target = pathlib.Path(folder) / 'grad.exr', pathlib.Path(folder) / 'grad.pfm'
            subprocess.run([str(OIIOTOOL), '--pattern', 'fill:top=1,0,0:bottom=0,0,0', '3840x2160', '3', '-d', 'float', '-o', str(source)],
                           env=env, check=True, capture_output=True)
            pfm_files.through_tiff(lambda path: subprocess.run([str(OIIOTOOL), str(source), '-d', 'float', '--compression', 'none', '-o', str(path)],
                                                               env=env, check=True, capture_output=True), target)
            data = target.read_bytes()
        head_end = 0
        for _ in range(3):
            head_end = data.index(b'\n', head_end) + 1
        row = 3840 * 12
        # The first value of every 135th row, bottom first: rising from 0 to 1.
        reds = [struct.unpack('<f', data[head_end + y * row:head_end + y * row + 4])[0] for y in range(0, 2160, 135)]
        self.assertEqual(reds, sorted(reds))
        self.assertLess(reds[0], 0.01)
        self.assertGreater(reds[-1], 0.9)


PROGRAM = ROOT / 'runtime/release-0.5.5.1/moonlightipr/modo_composite.exe'


@unittest.skipUnless(OIIOTOOL.is_file() and PROGRAM.is_file(), 'needs the runtime oiiotool and compositor program')
class CompositeRows(unittest.TestCase):
    """A 3840 x 2160 render through the compositor program (a grade, so the program runs): its rows in order. oiiotool
    wrote the program's PFM inputs with their halves swapped."""

    def test_a_large_composite_keeps_its_rows_in_order(self):
        from moonray_modo import compositor, native
        from moonray_modo.pfm_files import run_step
        env = native.environment(OIIOTOOL.parent)
        built = {'nodes': {'a': {'type': 'input', 'parameters': {'buffer': 'beauty'}, 'inputs': {}},
                           'g': {'type': 'grade', 'parameters': {'exposure': 1.0}, 'inputs': {'image': 'a'}},
                           'out': {'type': 'output', 'parameters': {}, 'inputs': {'image': 'g'}}}, 'root': 'out'}
        with tempfile.TemporaryDirectory() as folder:
            source = pathlib.Path(folder) / 'beauty.exr'
            subprocess.run([str(OIIOTOOL), '--pattern', 'fill:top=1,0,0:bottom=0,0,0', '3840x2160', '3', '-d', 'float', '-o', str(source)],
                           env=env, check=True, capture_output=True)
            steps, result = compositor.jobs(built, {'beauty': str(source)}, {'beauty': 'beauty'}, folder, composite=str(PROGRAM))
            for args, target in steps:
                if args[0] == '@pfm':
                    run_step(args, target)
                    continue
                command = args[1:] if args[0] == '@run' else [str(OIIOTOOL)] + args
                subprocess.run(command, env=env, check=True, capture_output=True, timeout=300)
            small = pathlib.Path(folder) / 'small.pfm'
            # A picture this small is one block of oiiotool's rows: its PFM is right.
            subprocess.run([str(OIIOTOOL), str(result), '--ch', '0,1,2', '--resize', '16x16!', '-d', 'float', '-o', str(small)],
                           env=env, check=True, capture_output=True)
            reds = [row[0] for row in reversed(pfm_rows(small)[1])]   # bottom row first
        self.assertEqual(reds, sorted(reds))
        self.assertLess(reds[0], 0.2)
        self.assertGreater(reds[-1], 1.5)    # 1 at the top, an exposure of 1 doubles it


if __name__ == '__main__':
    unittest.main()
