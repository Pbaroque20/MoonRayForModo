"""Evaluate a material's inputs in an exported .rdla by hand: its ModoTextureMap graph with every image replaced by a
value given on the command line, so what a mask does to the albedo can be read without rendering.
Usage: eval_rdla_material.py <scene.rdla> <material name> <texture-substring=value> ... [--attr albedo]
An image whose texture path holds the substring reads that value (an alpha-only read reads 1 unless 'alpha:' is
given before the substring); others read 0.5."""
import re
import sys

path, material = sys.argv[1], sys.argv[2]
values, attrs = {}, ['albedo']
args = sys.argv[3:]
if '--attr' in args:
    i = args.index('--attr')
    attrs = args[i + 1].split(',')
    args = args[:i] + args[i + 2:]
for arg in args:
    key, value = arg.rsplit('=', 1)
    values[key] = float(value)
text = open(path, encoding='utf-8', errors='replace').read()
nodes = {}
for match in re.finditer(r'^(\w+)\("([^"]+)"\) \{\n(.*?)^\}', text, re.S | re.M):
    kind, name, body = match.groups()
    fields = {}
    for line in body.split('\n'):
        m = re.match(r'\s*\["(\w+)"\] = (.*?),?$', line)
        if m:
            fields[m.group(1)] = m.group(2)
    nodes[name] = (kind, fields)
start = text.index('materials["%s"] = DwaBaseMaterial(' % material)
block = text[start:text.index('\n}', start)]
roots = {m.group(1): m.group(2) for m in re.finditer(r'\["(\w+)"\] = (.*?),?\n', block)}


def triple(v):
    return v if isinstance(v, list) else [v, v, v]


def literal(expr):
    m = re.match(r'Rgb\(([^)]*)\)', expr)
    if m:
        return [float(x) for x in m.group(1).split(',')]
    try:
        return float(expr)
    except ValueError:
        return None


def value(expr):
    expr = expr.strip()
    m = re.match(r'bind\((\w+)\("([^"]+)"\), (.*)\)$', expr)
    if m:
        return node(m.group(2))
    lit = literal(expr)
    return 0.0 if lit is None else lit


def blend(mode, a, b):
    a, b = triple(a), triple(b)
    ops = {0: lambda x, y: y, 1: lambda x, y: x * y, 2: lambda x, y: x + y, 3: lambda x, y: x - y,
           4: lambda x, y: 1 - (1 - x) * (1 - y), 5: lambda x, y: x / y if y else 0}
    return [ops.get(mode, lambda x, y: y)(x, y) for x, y in zip(a, b)]


def node(name):
    kind, f = nodes[name]
    if kind == 'ImageMap':
        texture = f.get('texture', '')
        alpha = f.get('alpha_only') == 'true'
        for key, v in values.items():
            if key.startswith('alpha:'):
                if alpha and key[6:] in texture:
                    return v
            elif key in texture and not alpha:
                return v
        return 1.0 if alpha else 0.5
    if kind == 'ModoTextureMap':
        if 'mode' in f:
            return value(f.get('foreground', '0'))
        bg, fg = value(f.get('background', '0')), value(f.get('foreground', '0'))
        mixed = blend(int(float(f.get('blend', '0'))), bg, fg)
        k = float(f.get('opacity', '1'))
        if 'mask' in f:
            mask = value(f['mask'])
            k *= (sum(triple(mask)) / 3)
        out = [x + (y - x) * k for x, y in zip(triple(bg), mixed)]
        return out
    if kind == 'ColorCorrectGainOffsetMap':
        v = triple(value(f.get('input', '0')))
        return [x * float(f.get('gain', '1')) + float(f.get('offset', '0')) for x in v]
    if kind == 'ColorCorrectGammaMap':
        v = triple(value(f.get('input', '0')))
        g = float(f.get('gamma', '1'))
        return [max(x, 0) ** (1 / g) if g else x for x in v]
    if kind == 'OpMap':
        a, b = triple(value(f.get('op1', '0'))), triple(value(f.get('op2', '0')))
        op = int(float(f.get('operation', '0')))
        return [{0: x + y, 1: x - y, 2: x * y, 3: x / y if y else 0}.get(op, x) for x, y in zip(a, b)]
    return 0.5


for attr in attrs:
    result = value(roots[attr]) if attr in roots else None
    print('%-14s %s' % (attr, ' '.join('%.3f' % v for v in triple(result)) if result is not None else 'not bound'))
