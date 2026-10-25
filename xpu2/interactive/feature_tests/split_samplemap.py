"""Split shade::sampleMap's switch (shade_mapnodes.h) into one function a case, each X2_CALL (__noinline__ on the
device, inline on the host), the switch a dispatcher: OptiX compiles a function on one thread, and the switch with
every case inlined was the GPU program's largest function (49,000 PTX lines). split_samplemap.py <interactive>."""
import re
import sys
from pathlib import Path

p = Path(sys.argv[1]) / 'shade_mapnodes.h'
lines = p.read_text(encoding='utf-8').split('\n')
head = next(i for i, l in enumerate(lines) if l.startswith('X2_CALL U32 sampleMap(const MapNodeHeader& h, const MapParams& P, const State& st, const Tex& tex, Color& out) {'))
assert lines[head - 1] == 'template <class Tex>', lines[head - 1]
assert lines[head + 1] == '    switch (h.kind) {', lines[head + 1]
end = next(i for i in range(head + 2, len(lines)) if lines[i] == '    }' and lines[i + 1] == '}')
assert lines[end + 1] == '}', lines[end + 1]
body = lines[head + 2:end]

# Group the top-level case labels (4-space indent) with their bodies.
groups = []  # (labels, body lines)
default = None
i = 0
label = re.compile(r'^    case (Map[A-Za-z0-9_]+):(.*)$')
while i < len(body):
    line = body[i]
    if line.startswith('    default:'):
        default = line
        i += 1
        continue
    m = label.match(line)
    assert m, ('unexpected line', line)
    labels, rest = [m.group(1)], m.group(2).strip()
    while not rest and i + 1 < len(body) and label.match(body[i + 1]):
        i += 1
        m = label.match(body[i])
        labels.append(m.group(1))
        rest = m.group(2).strip()
    block = []
    if rest == '{' or re.match(r'^\{\s*//', rest):
        depth = 1
        if rest != '{':
            block.append('    ' + rest[1:].strip())
        i += 1
        while True:
            l = body[i]
            depth += l.count('{') - l.count('}')
            if depth == 0:
                assert l.strip() == '}', ('block end', l)
                break
            block.append(l[4:] if l.startswith('    ') else l)
            i += 1
        i += 1
    elif rest:
        block = ['    ' + rest]
        i += 1
    else:
        # A body on the following lines without braces, up to the next label.
        i += 1
        while i < len(body) and not label.match(body[i]) and not body[i].startswith('    default:'):
            block.append(body[i][4:] if body[i].startswith('    ') else body[i])
            i += 1
    joined = '\n'.join(block)
    nonblank = [l for l in block if l.strip()]
    assert nonblank, ("empty case", labels, rest)
    last = nonblank[-1].strip()
    assert 'return' in last, ('case does not end in a return', labels, last)
    groups.append((labels, block))
assert default is not None

functions, cases = [], []
for labels, block in groups:
    name = 'sampleMapCase' + labels[0][3:]
    functions += ['template <class Tex>',
                  'X2_CALL U32 %s(const MapNodeHeader& h, const MapParams& P, const State& st, const Tex& tex, Color& out) {' % name,
                  '    (void)h; (void)P; (void)st; (void)tex; (void)out;', '    {']
    functions += block
    functions += ['    }', '    return tex::Invalid;', '}']
    for l in labels:
        cases.append('    case %s: return %s(h, P, st, tex, out);' % (l, name))

out = lines[:head - 1]
out += ['// sampleMap\'s cases, one function each (X2_CALL: out of line on the device, so OptiX compiles them apart).']
out += functions
out += [lines[head - 1], lines[head], lines[head + 1]] + cases + [default] + lines[end:]
p.write_text('\n'.join(out), encoding='utf-8', newline='')
print(len(groups), 'case functions,', sum(len(g[0]) for g in groups), 'labels')
