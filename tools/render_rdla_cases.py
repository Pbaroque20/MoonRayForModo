"""Render RDLA scenes with a runtime's moonray.exe (scalar), each to the output its scene names, unless the picture is
newer than the scene; then print each picture's mean and largest red, green and blue, and, given a Modo picture named
modo_<case>.Final Color Output.0001.exr beside it, the ratio of the means.

render_rdla_cases.py <runtime> <folder> <case> [case ...]   (renders <folder>/<case>.rdla)"""
import re
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import native  # noqa: E402


def stats(runtime, environment, picture):
    text = subprocess.run([str(runtime / 'oiiotool.exe'), str(picture), '--printstats'], env=environment, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT).stdout.decode(errors='replace')
    found = {}
    for key in ('Avg', 'Max'):
        match = re.search(r'Stats %s: ([^\n(]+)' % key, text)
        found[key] = [float(v) for v in match.group(1).split()][:3] if match else None
    return found


def main():
    runtime, folder = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    environment = native.environment(runtime)
    for case in sys.argv[3:]:
        scene = folder / (case + '.rdla')
        text = scene.read_text(encoding='utf-8')
        match = re.search(r'\["output"\]\s*=\s*"([^"]+)"', text) or re.search(r'moonray_[^"]+\.exr', text)
        picture = folder / ('moonray_%s.exr' % case)
        if not picture.is_file() or picture.stat().st_mtime < scene.stat().st_mtime:
            done = subprocess.run([str(runtime / 'moonray.exe'), '-in', str(scene), '-out', str(picture), '-exec_mode', 'scalar'],
                                  env=environment, cwd=str(folder), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            (folder / (case + '.log')).write_bytes(done.stdout)
            if done.returncode or not picture.is_file():
                print('%s did not render:\n%s' % (case, done.stdout.decode(errors='replace')[-2000:]))
                continue
        ours = stats(runtime, environment, picture)
        line = '%-18s moonray avg %s max %s' % (case, ['%.4f' % v for v in ours['Avg']], ['%.4f' % v for v in ours['Max']])
        modo = folder / ('modo_%s.Final Color Output.0001.exr' % case)
        if modo.is_file():
            theirs = stats(runtime, environment, modo)
            line += '\n%-18s modo    avg %s max %s  ratio modo/moonray %s' % ('', ['%.4f' % v for v in theirs['Avg']], ['%.4f' % v for v in theirs['Max']],
                                                                             ['%.3f' % (a / b if b else 0) for a, b in zip(theirs['Avg'], ours['Avg'])])
        print(line)


if __name__ == '__main__':
    main()
