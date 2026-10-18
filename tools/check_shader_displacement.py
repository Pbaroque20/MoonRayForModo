"""Render the scenes tools/probe_shader_displacement.py exported with MoonRay and compare each with Modo's own render
of it. What is compared is where the sphere is (its pixels brighter than the black world): a displacement moves its
outline and a stencil cuts holes in it, so the share of the frame it covers and how much of that agrees say how
closely the plugin follows Modo. A picture of each pair, Modo left and MoonRay right, is written beside them.
Usage: check_shader_displacement.py <runtime>"""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))
from check_fresnel import pixels  # noqa: E402  (sets the plugin's modules up without Modo)
from moonray_modo import native  # noqa: E402

folder = root / 'test-results/shader-displacement'


def covered(values):
    return [max(values[i:i + 3]) > 0.01 for i in range(0, len(values), 3)]


runtime = native.find_runtime(sys.argv[1])
for case in ('displace', 'stencil'):
    scene = folder / (case + '.rdla')
    output = folder / ('moonray_' + case + '.exr')
    done = subprocess.run([str(runtime / 'moonray.exe'), '-in', str(scene), '-out', str(output), '-exec_mode', 'scalar'],
                          env=native.environment(runtime), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if done.returncode or not output.is_file():
        print(case, 'did not render:', done.stdout.decode(errors='replace')[-600:])
        continue
    modo = next(folder.glob('modo_%s*.exr' % case))
    w, h, ours = pixels(runtime, output)
    w2, h2, theirs = pixels(runtime, modo)
    a, b = covered(ours), covered(theirs)
    both = sum(x and y for x, y in zip(a, b))
    either = sum(x or y for x, y in zip(a, b))
    print('%-9s Modo covers %.1f%%, MoonRay %.1f%%; they agree on %.1f%% of what either covers'
          % (case, 100 * sum(b) / len(b), 100 * sum(a) / len(a), 100 * both / max(1, either)), flush=True)
    subprocess.run([str(runtime / 'oiiotool.exe'), str(modo), '--ch', 'R,G,B', str(output), '--ch', 'R,G,B', '--mosaic', '2x1',
                    '--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o', str(folder / ('pair_' + case + '.png'))],
                   env=native.environment(runtime), check=True)
