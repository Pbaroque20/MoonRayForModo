"""Render the scenes tools/probe_native_light_links.py exported with MoonRay, and compare each square's brightness with
Modo's own render of the same light link. The environment is black, so a square the light does not reach is dark.

Expected: with the left square excluded from the light, it is dark and the right one lit; included, the other way
round. Usage: check_native_light_links.py <moonray-runtime>"""
import json
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))
from check_fresnel import pixels  # noqa: E402  (also sets the plugin's modules up without Modo)
from moonray_modo import native  # noqa: E402

folder = root / 'test-results/native-light-links'


def squares(runtime, source):
    width, height, values = pixels(runtime, source)
    def mean(x0, x1):
        found = [values[(y * width + x) * 3 + 1] for y in range(height // 3, 2 * height // 3) for x in range(x0, x1)]
        return sum(found) / len(found)
    return mean(width // 4 - 6, width // 4 + 6), mean(3 * width // 4 - 6, 3 * width // 4 + 6)


def main():
    runtime = Path(sys.argv[1]).resolve()
    report = json.loads((folder / 'report.json').read_text())
    for case, dark in (('exclude', 'left'), ('include', 'right')):
        entry = report['cases'].get(case, {})
        if entry.get('error'):
            print(case, entry['error'][-300:])
            continue
        output = folder / ('moonray_' + case + '.exr')
        done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(folder / (case + '.rdla'), output, 0, 'vectorized'),
                              env=native.environment(runtime), cwd=str(folder), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if done.returncode or not output.is_file():
            print(case, 'MoonRay failed:', done.stdout.decode(errors='replace')[-300:])
            continue
        theirs = squares(runtime, folder / ('modo_' + case + '.Final Color Output.0001.exr'))
        ours = squares(runtime, output)
        def says(pair):
            return 'left %s, right %s' % tuple('dark' if v < .02 else 'lit (%.2f)' % v for v in pair)
        same = all((a < .02) == (b < .02) for a, b in zip(theirs, ours))
        print('%-8s Modo: %-32s MoonRay: %-32s %s' % (case, says(theirs), says(ours), 'same' if same else 'DIFFERENT'))
        print('         links captured: %s' % entry.get('links'))


if __name__ == '__main__':
    main()
