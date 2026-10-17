"""A soak of every native MoonRay material the plugin offers, without Modo: each is written by the plugin's own scene
writer (rdla.scene_text, the path a material assigned in Modo takes) onto the two boxes of a captured scene, and rendered
by MoonRay from the command line three times: with its defaults (vector mode), with every attribute that can be set
safely given a value other than its default (vector mode), and the same in scalar mode. For each render: MoonRay's exit
code and errors, whether each attribute set reached the scene file, and whether the picture is finite and not black;
and whether setting the attributes changed the picture.

soak_materials.py [<runtime>] [material ...]     (writes test-results/material-soak/report.json and report.md)"""
import array
import json
import math
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import native, rdla, shader_library  # noqa: E402

RUNTIME = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 and pathlib.Path(sys.argv[1]).is_dir() else \
    pathlib.Path.home() / 'AppData/Roaming/Luxology/Kits/MoonRayForModo/runtime'
ONLY = [a for a in sys.argv[1:] if not pathlib.Path(a).is_dir()]
OUT = ROOT / 'test-results/material-soak'
OUT.mkdir(parents=True, exist_ok=True)
WIDTH, HEIGHT, GRID = 160, 90, 2
# Attributes not set: what names a light set or labels, rather than how the surface looks.
LEFT_ALONE = re.compile(r'lightset|label|^extra_aovs$|cryptomatte|_aov|^priority$')


def changed_value(name, spec):
    """A valid value other than the default for an attribute, or None for one not set by the soak."""
    kind, default = spec['type'], spec.get('default')
    if LEFT_ALONE.search(name):
        return None
    try:
        if kind == 'Bool':
            return not (str(default).lower() == 'true')
        if kind == 'Rgb':
            return [0.8, 0.3, 0.1] if '0.8' not in str(default) else [0.2, 0.5, 0.9]
        if kind == 'Float':
            value = float(str(default).rstrip('f')) if default is not None else 0.0
            low = float(str(spec['min']).rstrip('f')) if 'min' in spec else None
            high = float(str(spec['max']).rstrip('f')) if 'max' in spec else None
            if low is not None and high is not None:
                other = low + (high - low) * (0.3 if value > low + (high - low) * 0.5 else 0.7)
            else:
                other = value + 0.2 if value < 50 else value * 0.8
            return float(other)
        if kind == 'Int' and 'enum' in spec:
            values = sorted({int(v) for v in spec['enum'].values()})
            current = int(str(default)) if default is not None and str(default).lstrip('-').isdigit() else values[0]
            others = [v for v in values if v != current]
            return others[0] if others else None
    except (TypeError, ValueError):
        return None
    return None


def material(shader, parameters, library_ref=None):
    return {'shader': 'DwaBaseMaterial', 'thin_geometry': False, 'moonshine_override': True, 'native_shader': shader,
            'native_parameters': parameters}


def children_for(shader, library):
    """Materials for the inputs a material takes others through (layers, mixes, switches): one of each kind it takes."""
    wired = {}
    for name, spec in shader_library.catalog()[shader]['attributes'].items():
        if spec['type'] != 'SceneObject*' or spec.get('interface', '') in ('', 'INTERFACE_GENERIC', 'INTERFACE_MAP', 'INTERFACE_NORMALMAP'):
            continue
        # Plain materials first: a material that takes others itself (an adjust, a layer) would be given none.
        takes_others = lambda name: any(s['type'] == 'SceneObject*' and s.get('interface', '') not in ('', 'INTERFACE_GENERIC', 'INTERFACE_MAP', 'INTERFACE_NORMALMAP')
                                        for s in shader_library.catalog()[name]['attributes'].values())
        preferred = ['DwaBaseMaterial', 'HairMaterial_v3'] + sorted(n for n in library if not takes_others(n))
        for candidate in preferred:
            if candidate != shader and shader_library.compatible(candidate, spec.get('interface', '')):
                wired[name] = {'material': 'child_' + candidate}
                break
    return wired


def read_pfm(path):
    data = pathlib.Path(path).read_bytes()
    parts, at = [], 0
    while len(parts) < 3:
        end = data.index(b'\n', at)
        parts.append(data[at:end].strip())
        at = end + 1
    width, height = (int(v) for v in parts[1].split())
    values = array.array('f')
    values.frombytes(data[at:at + width * height * 12])
    if (float(parts[2]) > 0) != (sys.byteorder == 'big'):
        values.byteswap()
    return values


def render(scene, name, mode):
    exr, rdla_path, pfm = OUT / (name + '.exr'), OUT / (name + '.rdla'), OUT / (name + '.pfm')
    text = rdla.scene_text(scene, WIDTH, HEIGHT, GRID, 0.4, str(exr))
    rdla_path.write_text(text)
    began = time.time()
    done = subprocess.run([str(RUNTIME / 'moonray.exe')] + native.arguments(str(rdla_path), str(OUT / (name + '_main.exr')), 0, mode),
                          env=native.environment(RUNTIME), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
    log = done.stdout.decode(errors='replace')
    errors = sorted({line.split('|')[-1].strip()[:200] for line in log.splitlines()
                     if re.search(r'\berror\b|fatal|exception|invalid|unknown attribute|not a valid|could not', line, re.I)
                     and 'Target adaptive error' not in line and 'error_' not in line and 'Broken or invalid files: 0' not in line})
    result = {'exit': done.returncode, 'seconds': round(time.time() - began, 1), 'errors': errors, 'text': text}
    if exr.is_file():
        subprocess.run([str(RUNTIME / 'oiiotool.exe'), str(exr), '--ch', 'R,G,B', '-d', 'float', '-o', str(pfm)], env=native.environment(RUNTIME),
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        subprocess.run([str(RUNTIME / 'oiiotool.exe'), str(exr), '--ch', 'R,G,B', '--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o',
                        str(OUT / (name + '.png'))], env=native.environment(RUNTIME), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if pfm.is_file():
        values = read_pfm(pfm)
        finite = [v for v in values if math.isfinite(v)]
        result.update(nonfinite=len(values) - len(finite), mean=sum(finite) / max(1, len(finite)), pixels=values)
    return result


def main():
    catalog = shader_library.catalog()
    base = json.loads((ROOT / 'test-results/doc-camera-material/modo_camera.json').read_text())
    base['render_settings'] = {'sampling_mode': 0}
    # A plain grey floor; the boxes take the material soaked.
    floor_tag, box_tags = 'soak_floor', 'soak_box'
    library = {('child_' + shader): material(shader, {}) for shader in catalog}
    names = [n for n in sorted(catalog) if not ONLY or n in ONLY]
    report = {}
    for shader in names:
        changed, skipped = {}, []
        for name, spec in catalog[shader]['attributes'].items():
            value = changed_value(name, spec)
            if value is None:
                if spec['type'] != 'SceneObject*':
                    skipped.append(name)
                continue
            try:
                shader_library.validate(shader, {name: value})
                changed[name] = value
            except ValueError:
                skipped.append(name)
        inputs = children_for(shader, catalog)
        entry = {'set': sorted(changed), 'left_alone': skipped, 'inputs': {k: v['material'][6:] for k, v in inputs.items()}}
        for variant, parameters, mode in (('default', dict(inputs), 'vectorized'), ('changed', dict(inputs, **changed), 'vectorized'),
                                          ('changed_scalar', dict(inputs, **changed), 'scalar')):
            scene = json.loads(json.dumps(base))
            scene['materials'] = {floor_tag: material('DwaBaseMaterial', {'albedo': [0.5, 0.5, 0.5]}), box_tags: material(shader, parameters)}
            scene['native_materials'] = library
            for index, mesh in enumerate(scene['meshes']):
                mesh['material'] = floor_tag if index == 0 else box_tags
            name = '%s_%s' % (shader, variant)
            try:
                done = render(scene, name, mode)
            except Exception as exc:  # the scene writer refused it
                entry[variant] = {'writer_error': str(exc)}
                continue
            text = done.pop('text')
            missing = [key for key in (changed if variant != 'default' else {}) if '["%s"]' % key not in text]
            done['not_in_scene_file'] = missing
            entry[variant] = done
        a, b = entry.get('default', {}).get('pixels'), entry.get('changed', {}).get('pixels')
        if a is not None and b is not None and len(a) == len(b):
            entry['changed_vs_default'] = sum(abs(x - y) for x, y in zip(a, b) if math.isfinite(x) and math.isfinite(y)) / len(a)
        for variant in ('default', 'changed', 'changed_scalar'):
            entry.get(variant, {}).pop('pixels', None)
        problems = []
        for variant in ('default', 'changed', 'changed_scalar'):
            got = entry.get(variant, {})
            if 'writer_error' in got:
                problems.append('%s: the scene writer refused it: %s' % (variant, got['writer_error']))
                continue
            if got.get('exit'):
                problems.append('%s: MoonRay exited %s' % (variant, got['exit']))
            if got.get('errors'):
                problems.append('%s: %d error line(s): %s' % (variant, len(got['errors']), got['errors'][0]))
            if got.get('nonfinite'):
                problems.append('%s: %d non-finite values' % (variant, got['nonfinite']))
            if got.get('mean', 1) <= 1e-6:
                problems.append('%s: black picture' % variant)
            if got.get('not_in_scene_file'):
                problems.append('%s: set but not written: %s' % (variant, ', '.join(got['not_in_scene_file'])))
        if entry.get('changed_vs_default') is not None and entry['changed_vs_default'] < 1e-6:
            problems.append('setting %d attributes changed nothing in the picture' % len(changed))
        entry['problems'] = problems
        report[shader] = entry
        print('%-28s %s' % (shader, 'OK' if not problems else '; '.join(problems)[:300]), flush=True)
        (OUT / 'report.json').write_text(json.dumps(report, indent=1, default=str))
    lines = ['# Material soak', '', 'Runtime: `%s`, %d x %d, pixel samples %d squared.' % (RUNTIME, WIDTH, HEIGHT, GRID), '',
             '| Material | Attributes set | Inputs wired | Changed vs default | Problems |', '|---|---|---|---|---|']
    for shader, entry in report.items():
        lines.append('| %s | %d | %s | %s | %s |' % (shader, len(entry['set']), ', '.join('%s: %s' % kv for kv in entry['inputs'].items()) or '-',
                                                     '%.4f' % entry['changed_vs_default'] if entry.get('changed_vs_default') is not None else '-',
                                                     '<br>'.join(entry['problems']) or 'none'))
    (OUT / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
