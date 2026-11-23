"""Score a finished run_rhea.py output against a reference made afterwards: its films' errors into report.json.

score.py <run_rhea output> <reference.rgba>

Scores final, phase2, recon, sequence-final, xpu2-<n>, accum-<K>, naive-<K> and xpu2-accum-<K> where present, as
run_rhea.py does with --reference, and prints one line each."""
import json
import sys
from pathlib import Path

from images import errors, read_rgba


def main():
    out, reference = Path(sys.argv[1]), Path(sys.argv[2])
    report = json.loads((out / 'report.json').read_text(encoding='utf-8'))
    w, h = report['width'], report['height']
    ref = read_rgba(reference, w, h)
    names = [n for n in ('final', 'phase2', 'recon', 'sequence-final') if (out / (n + '.rgba')).exists()]
    for prefix in ('xpu2-', 'accum-', 'naive-', 'xpu2-accum-'):
        names += sorted((f.stem for f in out.glob(prefix + '*.rgba') if f.stem[len(prefix):].isdigit()),
                        key=lambda n: int(n.split('-')[-1]))
    report['errors'] = {n: errors(read_rgba(out / (n + '.rgba'), w, h), ref, w, h) for n in names}
    report['reference'] = str(reference)
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    for n, e in report['errors'].items():
        print(f"{n:16s} relative MSE {e['relative_mse']:.3e}  block {e['block_error']:.3e}  mean ratio {e['mean_ratio']:.5f}")


if __name__ == '__main__':
    main()
