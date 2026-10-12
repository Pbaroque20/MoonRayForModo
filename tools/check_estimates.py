"""Replay a recorded render through the time-left estimate and set it beside what was really left.

Usage: check_estimates.py [name ...] [--trace]
Reads test-results/estimates/<name>.json (tools/probe_estimates.py). The progress reports are fed to
moonray_modo.progress.Progress at the times they came, with its clock driven from the recording, and once a second the
estimate is compared with the time that was in truth left until the render ended. Says how far off it was, how much it
jumped from one second to the next, and its worst moments. --trace prints every fifth second."""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import progress


def replay(name, trace=False):
    held = json.loads((ROOT / 'test-results/estimates' / (name + '.json')).read_text())
    fed, passes, end = held['fed'], sorted(set(held['passes'])), held['took']
    now = [0.0]
    state = progress.Progress(clock=lambda: now[0])
    plan = held.get('plan')
    if plan and hasattr(state, 'plan'):
        state.plan(plan, held.get('adaptive', False))
    rows, index, upcoming = [], 0, list(passes)
    second = 1.0
    while second < end:
        while upcoming and upcoming[0] <= second:
            now[0] = upcoming.pop(0)
            state.reset_pass()
        while index < len(fed) and fed[index][0] <= second:
            now[0] = fed[index][0]
            state.feed(fed[index][1])
            index += 1
        now[0] = second
        value, label = state.display('render')
        found = re.search(r'About (?:(\d+)h )?(\d+)m (\d+)s left', label)
        shown = (int(found.group(1) or 0) * 3600 + int(found.group(2)) * 60 + int(found.group(3))) if found else None
        rows.append((second, end - second, shown, value, label))
        second += 1.0
    told = [(t, truth, shown) for t, truth, shown, _, _ in rows if shown is not None]
    if not told:
        print('%-22s render %4.0f s | no time left was shown; it said: %s' % (name, end, rows[len(rows) // 2][4].encode('ascii', 'replace').decode()))
        return
    ratios = sorted(max(shown, 1) / max(truth, 1) for _, truth, shown in told)
    errors = sorted(abs(shown - truth) for _, truth, shown in told)
    # A steady estimate falls by a second each second: anything else is a jump.
    jumps = sorted(abs((b[2] - a[2]) + (b[0] - a[0])) for a, b in zip(told, told[1:]))
    rises = sum(1 for a, b in zip(told, told[1:]) if b[2] > a[2] + 2)
    print('%-22s render %4.0f s | shown for %3d of %3d s | off by: median %4.0f s, worst %5.0f s | shown/true: %.2f to %.2f | jump a second: median %.1f, worst %.0f | rose %d times'
          % (name, end, len(told), len(rows), errors[len(errors) // 2], errors[-1], ratios[0], ratios[-1], jumps[len(jumps) // 2] if jumps else 0, jumps[-1] if jumps else 0, rises))
    if trace:
        for t, truth, shown, value, label in rows[::5]:
            print('   %4.0f s  true %4.0f  shown %s  %s%%  %s' % (t, truth, '%4d' % shown if shown is not None else '   -', value, label.encode('ascii', 'replace').decode()))


if __name__ == '__main__':
    names = [word for word in sys.argv[1:] if not word.startswith('--')] or sorted(p.stem for p in (ROOT / 'test-results/estimates').glob('*.json'))
    for name in names:
        replay(name, '--trace' in sys.argv)
