"""A reference image: XPU2 at the scene's own samples a pixel, rendered with several seeds and averaged.

make_reference.py --build <async build> --scene <scene.rdla> --output <new folder> [--seeds 16] [--extra <.rdla>]

Averaging seeds rather than raising the sample count keeps the scene's texture filtering: MoonRay and XPU2 narrow a
texture's filter as the samples a pixel grow (the ray differentials scale by them), so a 1024-sample render is sharper
than the converged image of a 64-sample scene. Writes reference.rgba and reference.png."""
import argparse
import json
from array import array
from pathlib import Path
from types import SimpleNamespace

from images import read_rgba, write_png, write_rgba
from run_xpu2_baseline import REFERENCE, run


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build', type=Path, required=True)
    p.add_argument('--scene', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seeds', type=int, default=16)
    p.add_argument('--extra', type=Path)
    a = p.parse_args()
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    total, w, h, seconds = None, 0, 0, []
    for s in range(a.seeds):
        rep = run(SimpleNamespace(build=a.build, scene=a.scene, output=out / f'seed-{s + 1}', runtime=REFERENCE, threads=12,
                                  repeats=1, mode=2, override=a.extra, seed=1000 + s))
        w, h = rep['width'], rep['height']
        img = read_rgba(Path(rep['runs'][0]['raw_file']), w, h)
        total = array('d', img) if total is None else array('d', (t + v for t, v in zip(total, img)))
        seconds.append(rep['runs'][0]['sampling_seconds'])
    ref = array('f', (v / a.seeds for v in total))
    write_rgba(out / 'reference.rgba', ref)
    write_png(out / 'reference.png', ref, w, h)
    (out / 'reference.json').write_text(json.dumps({'seeds': a.seeds, 'width': w, 'height': h, 'sampling_seconds': seconds}, indent=2),
                                        encoding='utf-8')
    print(json.dumps({'seeds': a.seeds, 'mean_sampling_seconds': sum(seconds) / len(seconds)}))


if __name__ == '__main__':
    main()
