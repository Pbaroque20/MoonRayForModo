"""What probe_moonlightipr_export_aovs.py exported from MoonLightIPR, checked against the numbers MoonLightIPR sent:
each EXR (32-bit float) pixel for pixel against its output's numbers (the beauty against the last picture sent under
the beauty's name, which is the denoised one where that was exported last); the beauty's alpha against the Alpha AOV;
the multilayer EXR's beauty and each of its layers against the EXRs on their own; and the PNG run holding only the
outputs ticked. check_moonlightipr_export_aovs.py <runtime folder>"""
import array
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import native

runtime = native.find_runtime(sys.argv[1])
env = native.environment(runtime)
tool = str(runtime / 'oiiotool.exe')
folder = ROOT / 'test-results/moonlightipr-export-aovs'
report = json.loads((folder / 'report.json').read_text())


def pfm(path):
    data = path.read_bytes().split(b'\n', 3)
    width, height = map(int, data[1].split())
    values = array.array('f')
    values.frombytes(data[3][:width * height * 12])
    return width, height, values


def channels(path, names):
    """Those channels of an EXR as a PFM's numbers (rows as PFM keeps them)."""
    target = folder / '_check.pfm'
    done = subprocess.run([tool, str(path), '--ch', ','.join(names), '-d', 'float', '-o', str(target)], env=env, capture_output=True)
    if done.returncode:
        raise RuntimeError(done.stderr.decode(errors='replace')[-300:])
    held = pfm(target)
    target.unlink()
    return held


def names_of(path):
    text = subprocess.run([tool, '--info', '-v', str(path)], env=env, capture_output=True, text=True).stdout
    line = next(l for l in text.splitlines() if 'channel list' in l)
    return [n.strip() for n in line.split(':', 1)[1].split(',')]


def largest(a, b):
    return max(abs(x - y) for x, y in zip(a, b)) if len(a) == len(b) else float('inf')


worst = 0.0
exr = folder / 'exr32'
print('== each EXR against what MoonLightIPR sent')
for sent in sorted(folder.glob('sent_*.pfm')):
    key = sent.stem[len('sent_'):]
    target = exr / ('probe_%s.exr' % key)
    if not target.is_file():
        print('   %-24s no EXR' % key)
        continue
    w, h, numbers = pfm(sent)
    ew, eh, written = channels(target, ['R', 'G', 'B'])
    # The sent picture's rows may run the other way round from the EXR's.
    flipped = array.array('f')
    for row in reversed(range(h)):
        flipped.extend(numbers[row * w * 3:(row + 1) * w * 3])
    off = min(largest(numbers, written), largest(flipped, written))
    worst = max(worst, off)
    print('   %-24s %dx%d  largest difference %.6f' % (key, ew, eh, off))
beauty = exr / 'probe_beauty.exr'
print('   beauty channels: %s' % ', '.join(names_of(beauty)))
alpha = channels(beauty, ['A', 'A', 'A'])[2]
coverage = channels(exr / 'probe_alpha.exr', ['R', 'G', 'B'])[2]
print('   beauty alpha against the Alpha AOV: largest difference %.6f' % largest(alpha, coverage))

print('== the multilayer EXR against the EXRs on their own')
layered = folder / 'exr32_layered' / 'probe.exr'
held = names_of(layered)
layers = sorted({n.rsplit('.', 1)[0] for n in held if '.' in n})
print('   layers: %s' % ', '.join(layers))
off = largest(channels(layered, ['R', 'G', 'B', 'A'])[2], channels(beauty, ['R', 'G', 'B', 'A'])[2])
worst = max(worst, off)
print('   %-24s largest difference %.6f' % ('beauty (R, G, B, A)', off))
for layer in layers:
    single = exr / ('probe_%s.exr' % layer)
    if not single.is_file():
        print('   %-24s no EXR of its own' % layer)
        continue
    off = largest(channels(layered, ['%s.R' % layer, '%s.G' % layer, '%s.B' % layer])[2], channels(single, ['R', 'G', 'B'])[2])
    worst = max(worst, off)
    print('   %-24s largest difference %.6f' % (layer, off))

print('== what each run asked and wrote')
for label, entry in report['exports'].items():
    print('   %-12s chosen %s; asked of the session %s; buffer list changed %s; files %s'
          % (label, entry.get('chosen'), entry.get('asked_of_session'), entry.get('buffer_list_changes'), entry.get('files')))
print('largest difference anywhere: %.6f' % worst)
