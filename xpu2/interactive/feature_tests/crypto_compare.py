"""crypto_compare.py <ref.exr> <a.exr> [<noise.exr>]: Cryptomatte parts compared fragment by fragment.
For each part with Cryptomatte channels: per pixel, the coverage by ID (Cryptomatte NN R/G and B/A pairs); the mean
over pixels of sum |coverage_a(id) - coverage_ref(id)| (0: equal, 2: disjoint), the share of pixels whose leading ID
differs, the fragment count, and CryptoS (presence depth and sample count) by ID; beside the noise floor's."""
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL = r'C:\Users\Raphael Tobar\AppData\Roaming\Luxology\Kits\MoonRayForModo\runtime\oiiotool.exe'
TMP = Path(tempfile.mkdtemp())


def parts(exr):
    out = subprocess.run([TOOL, '--info', '-v', '-a', str(exr)], capture_output=True, text=True).stdout
    res = []
    for block in re.split(r'subimage\s+\d+:', out)[1:] if re.search(r'subimage\s+\d+:', out) else [out]:
        m = re.search(r'channel list:\s*(.+)', block)
        n = re.search(r'\n\s+name:\s*"([^"]+)"', block)
        res.append((n.group(1) if n else '', [re.sub(r'\s*\(.*\)$', '', c.strip()) for c in m.group(1).split(',')] if m else []))
    return res


def load(exr, sub, chans):
    vals = {}
    for i in range(0, len(chans), 3):
        group = chans[i:i + 3]
        spec = ','.join(group + ['pad%d=0' % k for k in range(3 - len(group))])
        pfm = TMP / 'c.pfm'
        subprocess.run([TOOL, str(exr), '--subimage', str(sub), '--ch', spec, '-d', 'float', '-o', str(pfm)], capture_output=True, check=True)
        data = pfm.read_bytes()
        p = data.split(b'\n', 3)
        w, h = map(int, p[1].split())
        v = struct.unpack('<%df' % (w * h * 3), p[3][:w * h * 12])
        for k, c in enumerate(group):
            vals[c] = v[k::3]
    return w, h, vals


def fragments(vals, layers, pixel, prefix):
    f = []
    for l in range(layers):
        for a, b in (('R', 'G'), ('B', 'A')):
            i, c = vals['%s%02d.%s' % (prefix, l, a)][pixel], vals['%s%02d.%s' % (prefix, l, b)][pixel]
            if c != 0.0 or i != 0.0:
                f.append((i, c))
    return f


def stats(ref, a, layers, pixels, prefix, sref=None, sa=None):
    diff = lead = cnt_r = cnt_a = 0.0
    sdiff = 0
    for p in range(pixels):
        fr, fa = fragments(ref, layers, p, prefix), fragments(a, layers, p, prefix)
        cr, ca = {}, {}
        for i, c in fr: cr[i] = cr.get(i, 0.0) + c
        for i, c in fa: ca[i] = ca.get(i, 0.0) + c
        diff += sum(abs(ca.get(i, 0.0) - cr.get(i, 0.0)) for i in set(cr) | set(ca))
        if (fr[0][0] if fr else None) != (fa[0][0] if fa else None): lead += 1
        cnt_r += len(fr)
        cnt_a += len(fa)
    return diff / pixels, lead / pixels, cnt_r / pixels, cnt_a / pixels


ref, a = sys.argv[1], sys.argv[2]
noise = sys.argv[3] if len(sys.argv) > 3 else None
pr, pa = parts(ref), parts(a)
for s, (name, chans) in enumerate(pr):
    crypto = [c for c in chans if re.match(r'Cryptomatte(Reflect|Refract)?\d\d\.[RGBA]$', c)]
    if not crypto: continue
    sa = next((k for k, q in enumerate(pa) if q[0] == name), s)
    other = pa[sa] if sa < len(pa) else ('', [])
    print('part %d %r (a: %r): %d Cryptomatte channels%s' % (s, name, other[0], len(crypto), '' if other[1] == chans else ' -- channel lists differ'))
    layers = len([c for c in crypto if c.startswith('Cryptomatte') and c[11:13].isdigit() and c.endswith('.R') and not c.startswith('CryptomatteRe')])
    w, h, R = load(ref, s, chans)
    _, _, A = load(a, sa, chans)
    res = stats(R, A, layers, w * h, 'Cryptomatte')
    line = '  coverage |diff| %.4f  leading id differs %.4f  fragments ref %.3f a %.3f' % res
    if noise:
        _, _, N = load(noise, next((k for k, q in enumerate(parts(noise)) if q[0] == name), s), chans)
        line += '   | noise %.4f %.4f %.3f' % stats(R, N, layers, w * h, 'Cryptomatte')[:3]
    print(line)
    # Extra data by fragment slot (CryptoP, N, B, S...): mean absolute difference where both have the slot's ID.
    for tag in ('P', 'P0', 'N', 'B', 'RefP', 'RefN', 'UV', 'S'):
        names = [c for c in chans if re.match(r'Crypto%s\d\d\.[RGBA]$' % tag, c)]
        if not names: continue
        d = n = 0.0
        for p in range(w * h):
            fr, fa = fragments(R, layers, p, 'Cryptomatte'), fragments(A, layers, p, 'Cryptomatte')
            ida = {i: k for k, (i, _) in enumerate(fa)}
            for k, (i, _) in enumerate(fr):
                if i not in ida: continue
                for ch in 'RGBA':
                    cr, ca = 'Crypto%s%02d.%s' % (tag, k, ch), 'Crypto%s%02d.%s' % (tag, ida[i], ch)
                    if cr in R and ca in A:
                        d += abs(R[cr][p] - A[ca][p])
                        n += 1
        print('  Crypto%-5s mean |diff| by ID %.5f over %d values' % (tag, d / n if n else 0.0, n))
