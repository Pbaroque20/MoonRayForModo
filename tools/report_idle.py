"""Set the sampler's readings against the stretches of idleness probe_idle.py marked: for each stretch, the share of one
processor core each process used, and how busy the graphics card was. Run after the probe and the sampler have ended."""
import json
import pathlib

folder = pathlib.Path(__file__).resolve().parents[1] / 'test-results/idle'
marks = json.loads((folder / 'marks.json').read_text())
samples = [json.loads(line.lstrip('﻿')) for line in (folder / 'samples.jsonl').read_text(encoding='utf-8-sig').splitlines() if line.strip().startswith('{')]
for stretch in marks['stretches']:
    # Two seconds in from each end, so that what is switching on or off is not counted.
    inside = [s for s in samples if stretch['begin'] + 2 <= s['time'] <= stretch['end'] - 2]
    print('%s  (%s, %s)' % (stretch['name'], stretch['button'], stretch['status'][:50]))
    if len(inside) < 2:
        print('   too few readings')
        continue
    seconds = inside[-1]['time'] - inside[0]['time']
    for name in sorted(inside[-1]['cpu']):
        if name in inside[0]['cpu']:
            used = inside[-1]['cpu'][name] - inside[0]['cpu'][name]
            print('   %-32s %6.1f%% of one core' % (name, 100 * used / seconds))
    print('   graphics card busy %.0f%% on average (most %.0f%%), %.0f W, %.0f MB held' % (
        sum(s['gpu'] for s in inside) / len(inside), max(s['gpu'] for s in inside), sum(s['watts'] for s in inside) / len(inside), inside[-1]['memory']))
print(marks.get('errors') or marks.get('error') or '')
