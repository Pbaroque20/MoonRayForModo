"""Render the HDRI scenes tools/probe_hdri_turn.py wrote with MoonRay, and say which of Modo's own turns of the HDRI
each is nearest. A scene is its four views a quarter turn apart, the whole horizon; pictures are compared at the same
average brightness, by the average difference of their pixels. A plain HDRI at 0 should be nearest Modo's 0 and one at
90 nearest Modo's 90, as should the layered one. Usage: check_hdri_turn.py <runtime>"""
import json
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))
from check_fresnel import pixels  # noqa: E402  (sets the plugin's modules up without Modo)
from moonray_modo import native  # noqa: E402

folder = root / 'test-results/hdri-turn'
VIEWS = (0, 90, 180, 270)
MODO_TURNS = (0, 45, 90, 135, 180, 225, 270, 315)


def levelled(values):
    mean = sum(values) / max(1, len(values))
    return [v / max(1e-9, mean) for v in values]


def apart(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / max(1, len(a))


def report_nearest(engine, name, entry, ours, modo):
    distances = {degrees: apart(ours, picture) for degrees, picture in modo.items()}
    nearest = min(distances, key=distances.get)
    print('%-12s %-11s (%-5s) nearest Modo turn %3d   %s' % (engine, name, entry.get('environment_kind'), nearest,
                                                         '  '.join('%d:%.2f' % (d, distances[d]) for d in MODO_TURNS)), flush=True)


def moonlightipr_around(runtime, name):
    """The four views drawn by MoonLightIPR from the scenes as read (linear RGB, as the others), or None where
    MoonLightIPR is not built here."""
    import os
    os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
    try:
        import check_moonlightipr_session as fixture
    except Exception:
        return None
    fixture.WIDTH, fixture.HEIGHT = 192, 96
    session = fixture.Session(folder)
    found = []
    try:
        for view in VIEWS:
            scene = json.loads((folder / ('%s_%d.json' % (name, view))).read_text(encoding='utf-8'))
            # Linear RGB, three floats to a pixel.
            import struct
            data = bytes(session.submit(scene)['pixels'])
            found += struct.unpack('<%df' % (len(data) // 4), data)
    finally:
        try:
            session.process.stdin.write(b'quit\n'); session.process.stdin.flush(); session.process.wait(timeout=30)
        except Exception:
            pass
    return levelled(found)


def main():
    runtime = native.find_runtime(Path(sys.argv[1]))
    report = json.loads((folder / 'report.json').read_text())
    if report.get('error'):
        print(report['error'])

    def around(pattern, *name):
        found = []
        for view in VIEWS:
            found += pixels(runtime, folder / (pattern % (name + (view,))))[2]
        return levelled(found)
    modo = {degrees: around('modo_%d_%d.Final Color Output.0001.exr', degrees) for degrees in MODO_TURNS}
    for name, entry in report['exports'].items():
        if entry.get('error'):
            print(name, 'not written:', entry['error'].strip().splitlines()[-1])
            continue
        for view in VIEWS:
            output = folder / ('moonray_%s_%d.exr' % (name, view))
            subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(folder / ('%s_%d.rdla' % (name, view)), output, 0, 'vectorized'),
                           env=native.environment(runtime), cwd=str(folder), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
        ours = around('moonray_%s_%d.exr', name)
        report_nearest('MoonRay', name, entry, ours, modo)
        drawn = moonlightipr_around(runtime, name)
        if drawn is not None:
            report_nearest('MoonLightIPR', name, entry, drawn, modo)


if __name__ == '__main__':
    main()
