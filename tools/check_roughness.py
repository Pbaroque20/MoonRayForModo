"""Render the roughness scenes tools/probe_roughness.py exported with MoonRay and compare the highlights with Modo's.

For each Modo roughness: how far MoonRay's picture is from Modo's (the mean difference over the ball,
as a share of Modo's mean), and the two highlights' peaks. With "search", also try a range of MoonRay
roughness in Modo's place and report which comes closest, which is how the conversion was found.
Usage: check_roughness.py <moonray-runtime> [search]"""
import json
import re
import struct
import subprocess
import sys
import types
from pathlib import Path

root = Path(__file__).resolve().parents[1]
for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import native

folder = root / 'test-results/roughness'
CANDIDATES = [.03, .05, .08, .12, .16, .2, .25, .3, .35, .4, .45, .5, .55, .6, .65, .7, .75, .8, .85, .9, .95, 1.0]


def pixels(runtime, source):
    target = source.with_suffix('.pfm')
    subprocess.run([str(runtime / 'oiiotool.exe'), str(source), '--ch', 'R,G,B', '-d', 'float', '-o', str(target)], env=native.environment(runtime), check=True)
    data = target.read_bytes()
    parts = data.split(b'\n', 3)
    width, height = (int(v) for v in parts[1].split())
    values = struct.unpack(('<' if float(parts[2]) < 0 else '>') + '%df' % (width * height * 3), parts[3][:width * height * 12])
    return [values[i * 3 + 1] for i in range(width * height)]


def moonray(runtime, source, output):
    done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(source, output, 0, 'vectorized'), env=native.environment(runtime),
                          cwd=str(folder), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if done.returncode or not output.is_file():
        raise RuntimeError(done.stdout.decode(errors='replace')[-300:])
    return pixels(runtime, output)


def distance(ours, theirs):
    return sum(abs(a - b) for a, b in zip(ours, theirs)) / max(1e-9, sum(theirs))


def main():
    runtime = Path(sys.argv[1]).resolve()
    search = len(sys.argv) > 2 and sys.argv[2] == 'search'
    report = json.loads((folder / 'report.json').read_text())
    if 'error' in report:
        print(report['error'])
    found = {}
    for case in report['cases']:
        name = case['name']
        if 'error' in case:
            print(name, case['error'])
            continue
        theirs = pixels(runtime, folder / ('modo_' + name + '.Final Color Output.0001.exr'))
        ours = moonray(runtime, folder / (name + '.rdla'), folder / ('moonray_' + name + '.exr'))
        line = '%-15s Modo roughness %.2f: MoonRay off by %.3f, peak %.3f against Modo\'s %.3f' % (name, case['roughness'], distance(ours, theirs), max(ours), max(theirs))
        if search:
            text = (folder / (name + '.rdla')).read_text(encoding='utf-8')
            # The roughness is the first constant map after the albedo's; put each candidate in its place.
            block = re.search(r'ModoTextureMap\("/modo/graph/0/1"\) \{\n  \["background"\] = Rgb\([^)]*\),\n  \["foreground"\] = Rgb\(([^)]*)\),', text)
            scores = []
            for candidate in CANDIDATES:
                changed = text[:block.start(1)] + '%s, %s, %s' % (candidate, candidate, candidate) + text[block.end(1):]
                trial = folder / 'trial.rdla'
                trial.write_text(changed.replace('moonray_' + name + '.exr', 'trial.exr'), encoding='utf-8')
                scores.append((distance(moonray(runtime, trial, folder / 'trial.exr'), theirs), candidate))
            best = min(scores)
            found.setdefault(case['model'], []).append((case['roughness'], best[1], best[0]))
            line += '; closest MoonRay roughness %.2f (off by %.3f)' % (best[1], best[0])
        print(line, flush=True)
    for model, rows in found.items():
        print(model, [(a, b) for a, b, _ in rows])


if __name__ == '__main__':
    main()
