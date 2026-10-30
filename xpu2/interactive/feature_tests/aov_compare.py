"""aov_compare.py <ref.exr> <a.exr> [<noise.exr>]: every output of an EXR against MoonRay's, channel group by group.
Checks the files' layout (parts, channel names and order, half or float, compression, windows), then per group (the
channels before their last '.'): mean |a - ref| over the pixels relative to mean |ref|, the 8x8 block error, the mean
ratio, each beside the noise floor's (MoonRay's other frame)."""
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL = r'C:\Users\Raphael Tobar\AppData\Roaming\Luxology\Kits\MoonRayForModo\runtime\oiiotool.exe'
TMP = Path(tempfile.mkdtemp())


def info(exr):
    out = subprocess.run([TOOL, '--info', '-v', '-a', str(exr)], capture_output=True, text=True).stdout
    parts = []
    for block in re.split(r'\n(?=\S)|subimage\s+\d+:', out):
        m = re.search(r'channel list:\s*(.+)', block)
        if not m: continue
        chans = [c.strip() for c in m.group(1).split(',')]
        names = [re.sub(r'\s*\(.*\)', '', c) for c in chans]
        fmts = [re.search(r'\((\w+)\)', c).group(1) if '(' in c else '' for c in chans]
        comp = re.search(r'compression:\s*"?([^"\n]+)', block)
        part = re.search(r'\bname:\s*"([^"]+)"', block)
        size = re.search(r'(\d+\s*x\s*\d+)', block)
        win = re.search(r'full/display size:\s*([^\n]+)', block)
        attrs = sorted(l.strip() for l in block.split('\n') if re.match(r'\s+(cryptomatte/|MoonRayForModo/|comment|frameNumber)', l))
        parts.append({'names': names, 'formats': fmts, 'compression': comp.group(1).strip() if comp else '',
                      'part': part.group(1) if part else '', 'size': size.group(1) if size else '', 'display': win.group(1).strip() if win else '',
                      'attrs': attrs})
    return parts, out


def load(exr, chans, sub):
    pfm = TMP / 'x.pfm'
    spec = ','.join(chans + ['pad%d=0' % i for i in range(3 - len(chans))]) if len(chans) < 3 else ','.join(chans)
    r = subprocess.run([TOOL, str(exr), '--subimage', str(sub), '--ch', spec, '-o', str(pfm)], capture_output=True, text=True)
    if r.returncode: raise RuntimeError(r.stderr)
    data = pfm.read_bytes()
    p = data.split(b'\n', 3)
    w, h = map(int, p[1].split())
    v = struct.unpack('<%df' % (w * h * 3), p[3][:w * h * 12])
    return w, h, [v[i::3] for i in range(len(chans))]


def stats(ref, a, w, h):
    n = len(ref[0])
    finite = lambda x: x == x and abs(x) < 1e30
    num = den = 0.0
    sr = sa = 0.0
    bad = 0
    for c in range(len(ref)):
        for i in range(n):
            r, x = ref[c][i], a[c][i]
            if not finite(r) or not finite(x):
                if (r == r) != (x == x) or (abs(r) > 1e30) != (abs(x) > 1e30): bad += 1
                continue
            num += abs(x - r); den += abs(r); sr += r; sa += x
    blocks = []
    for by in range(h // 8):
        for bx in range(w // 8):
            br = ba = 0.0
            for y in range(by * 8, by * 8 + 8):
                for x in range(bx * 8, bx * 8 + 8):
                    i = y * w + x
                    for c in range(len(ref)):
                        if finite(ref[c][i]) and finite(a[c][i]): br += abs(ref[c][i]); ba += abs(a[c][i])
            if br > 0.02 * 64: blocks.append(abs(ba - br) / br)
    return {'abs': num / den if den else (0.0 if num == 0 else float('inf')), 'block': sum(blocks) / len(blocks) if blocks else 0.0,
            'ratio': sa / sr if sr else (1.0 if sa == 0 else float('inf')), 'bad': bad, 'mean': sr / n}


ref, a = sys.argv[1], sys.argv[2]
noise = sys.argv[3] if len(sys.argv) > 3 else None
rp, rinfo = info(ref)
ap, ainfo = info(a)
print('parts: ref %d, a %d' % (len(rp), len(ap)))
for s, (x, y) in enumerate(zip(rp, ap)):
    for k in ('part', 'compression', 'size', 'display', 'attrs'):
        if x[k] != y[k]: print('  part %d %s differs: ref %r, a %r' % (s, k, x[k], y[k]))
    if x['names'] != y['names']:
        print('  part %d channels differ:\n    ref %s\n    a   %s' % (s, x['names'], y['names']))
    elif x['formats'] != y['formats']:
        print('  part %d formats differ: %s' % (s, [(n, f, g) for n, f, g in zip(x['names'], x['formats'], y['formats']) if f != g]))
    else:
        print('  part %d: %d channels match in name, order and format' % (s, len(x['names'])))
for s, x in enumerate(rp):
    if s >= len(ap): break
    groups = {}
    for name in x['names']:
        groups.setdefault(name.rsplit('.', 1)[0] if '.' in name else ('beauty' if name in 'RGB' else name), []).append(name)
    for g, chans in groups.items():
        if any(c not in ap[s]['names'] for c in chans):
            print('%-14s missing in a' % g); continue
        for i in range(0, len(chans), 3):
            sub = chans[i:i + 3]
            w, h, R = load(ref, sub, s)
            _, _, A = load(a, sub, s)
            e = stats(R, A, w, h)
            line = '%-14s %-24s mean %10.4g  abs %.4f  block %.4f  ratio %.4f' % (g, ','.join(c.rsplit('.', 1)[-1] for c in sub)[:24], e['mean'], e['abs'], e['block'], e['ratio'])
            if e['bad']: line += '  inf/nan mismatches %d' % e['bad']
            if noise:
                _, _, N = load(noise, sub, s)
                f = stats(R, N, w, h)
                line += '   | noise abs %.4f  block %.4f  ratio %.4f' % (f['abs'], f['block'], f['ratio'])
                if f['bad']: line += ' bad %d' % f['bad']
            print(line, flush=True)
