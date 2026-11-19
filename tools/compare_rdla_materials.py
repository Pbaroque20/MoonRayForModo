"""Two materials of exported .rdla scenes side by side, input by input: each DwaBaseMaterial input's value (ModoTextureMap
graphs of constants evaluated; a RampMap's input and its output by its ramp; a material layer's mask), for the
material itself and the materials it layers. For finding why two materials with the same albedo render apart.
Usage: compare_rdla_materials.py <a.rdla> <material> <b.rdla> <material>"""
import re
import sys


def load(path):
    text = open(path, encoding='utf-8', errors='replace').read()
    nodes = {}
    for match in re.finditer(r'^(?:materials\["[^"]+"\] = )?(\w+)\("([^"]+)"\) \{\n(.*?)^\}', text, re.S | re.M):
        fields = dict(re.findall(r'\["(\w+)"\] = (.*?),?\n', match.group(3) + '\n'))
        nodes[match.group(2)] = (match.group(1), fields)
    for match in re.finditer(r'^(?:materials\["[^"]+"\] = )?(\w+)\("([^"]+)"\) \{ (.*?) \}$', text, re.M):
        fields = dict(re.findall(r'\["(\w+)"\] = ((?:[^,\[]|\[(?!")|,(?! \["))*)', match.group(3)))
        nodes[match.group(2)] = (match.group(1), {k: v.strip() for k, v in fields.items()})
    return text, nodes


def evaluator(nodes):
    def triple(v):
        return v if isinstance(v, list) else [v, v, v]

    def value(expr):
        expr = expr.strip()
        bound = re.match(r'bind\((\w+)\("([^"]+)"\), .*\)$', expr)
        if bound:
            return node(bound.group(2))
        rgb = re.match(r'Rgb\(([^)]*)\)', expr)
        if rgb:
            return [float(v) for v in rgb.group(1).split(',')]
        try:
            return [float(expr)] * 3
        except ValueError:
            return expr

    def ramp(fields, x):
        positions = [float(v) for v in fields['positions'].strip('{}').split(',')]
        colours = [float(m) for m in re.findall(r'Rgb\(([-\d.e]+),', fields['colors'])]
        for i in range(len(positions) - 1):
            if positions[i] <= x <= positions[i + 1]:
                t = (x - positions[i]) / (positions[i + 1] - positions[i])
                return colours[i] + (colours[i + 1] - colours[i]) * t
        return colours[-1] if x > positions[-1] else colours[0]

    def node(name):
        if name not in nodes:
            return '?' + name
        kind, f = nodes[name]
        if kind == 'ModoTextureMap':
            if 'mode' in f:
                return value(f.get('foreground', '0'))
            bg, fg = triple(value(f.get('background', '0'))), triple(value(f.get('foreground', '0')))
            if isinstance(bg[0], str) or isinstance(fg[0], str):
                return 'unread'
            mode = int(float(f.get('blend', '0')))
            ops = {0: lambda a, b: b, 1: lambda a, b: a * b, 2: lambda a, b: a + b, 3: lambda a, b: a - b, 5: lambda a, b: a / b if b else 0}
            mixed = [ops.get(mode, lambda a, b: b)(a, b) for a, b in zip(bg, fg)]
            k = float(f.get('opacity', '1'))
            if 'mask' in f:
                k *= sum(triple(value(f['mask']))) / 3
            return [a + (m - a) * k for a, m in zip(bg, mixed)]
        if kind == 'RampMap':
            x = triple(value(f['input']))[0]
            return [ramp(f, x)] * 3 if not isinstance(x, str) else 'unread'
        if kind == 'ColorCorrectGammaMap':
            v = triple(value(f['input']))
            g = float(f.get('gamma', '1'))
            return [max(a, 0) ** (1 / g) for a in v]
        if kind == 'ColorCorrectGainOffsetMap':
            v = triple(value(f['input']))
            return [a * float(f.get('gain', '1')) + float(f.get('offset', '0')) for a in v]
        return kind
    return value


def describe(path, material):
    text, nodes = load(path)
    value = evaluator(nodes)
    head = re.search(r'^materials\["%s"\] = (\w+)\("([^"]+)"\)' % re.escape(material), text, re.M)
    rows = {}
    seen = []

    def walk(name, prefix):
        if name in seen or name not in nodes:
            return
        seen.append(name)
        kind, fields = nodes[name]
        for key, expr in sorted(fields.items()):
            if key in ('material_A', 'material_B'):
                inner = re.search(r'\w+\("([^"]+)"\)', expr)
                target = inner.group(1) if inner else None
                if expr.startswith('materials['):
                    found = re.search(r'^materials\["%s"\] = \w+\("([^"]+)"\) \{\n' % re.escape(material), text, re.M)
                    target = found.group(1) if found else target
                rows[prefix + key] = target
                if target:
                    walk(target, prefix + key + '.')
                continue
            result = value(expr) if ('bind(' in expr or expr.startswith('Rgb(') or re.match(r'^-?[\d.]+$', expr)) else expr
            if isinstance(result, list):
                result = ' '.join('%.3f' % v for v in result) if len(set(round(v, 4) for v in result)) > 1 else '%.3f' % result[0]
            rows[prefix + key] = result
    walk(head.group(2), '')
    return rows


a = describe(sys.argv[1], sys.argv[2])
b = describe(sys.argv[3], sys.argv[4])
for key in sorted(set(a) | set(b)):
    left, right = a.get(key, '-'), b.get(key, '-')
    mark = '  <<' if str(left) != str(right) else ''
    print('%-46s %-24s %-24s%s' % (key[:46], str(left)[:24], str(right)[:24], mark))
