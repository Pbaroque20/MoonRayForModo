"""The layered, turned environment of tools/check_env_placement.py through MoonLightIPR: baked turned (as before)
and baked at rest with the turn given to the environment. The two pictures should be the same.
Usage: check_env_placement_moonlightipr.py <runtime> <hdri>"""
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))
import check_moonlightipr_session as fixture  # noqa: E402
from check_env_placement import scene  # noqa: E402
from moonray_modo import environment_layers, native  # noqa: E402

folder = root / 'test-results/hdri-rotation/moonlightipr'


def main():
    runtime = native.find_runtime(Path(sys.argv[1]))
    os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
    folder.mkdir(parents=True, exist_ok=True)
    value = scene(Path(sys.argv[2]), 90)
    pictures = {}
    keep = environment_layers.held_placement
    for label, held in (('held', keep), ('baked', lambda environment: None)):
        environment_layers.held_placement = held
        session = fixture.Session(folder)
        try:
            pictures[label] = session.submit(dict(value, meshes=[]))['pixels']
        finally:
            environment_layers.held_placement = keep
            session.process.stdin.write(b'quit\n'); session.process.stdin.flush(); session.process.wait(timeout=30)
    a, b = pictures['baked'], pictures['held']
    channels = [i for i in range(len(a)) if i % 4 != 3]
    difference = sum(abs(a[i] - b[i]) for i in channels) / len(channels)
    mean = sum(a[i] for i in channels) / len(channels)
    print('baked turned: average %.2f; at rest, turned whole: average %.2f; average difference %.2f (%.1f%% of the average)'
          % (mean, sum(b[i] for i in channels) / len(channels), difference, 100 * difference / max(1e-9, mean)))


if __name__ == '__main__':
    main()
