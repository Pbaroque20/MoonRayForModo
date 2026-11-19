"""Render the Group Mask scene as the plugin exported it (tools/probe_cl_group_mask_material.py) with MoonRay, and set
Modo's render above MoonRay's in one picture (pair.png). Each cube is a black Material under a group holding a purple
Material, the group masked by a Constant at 0.5 (Half), a Noise (Noise) or a Constant at 1 (Full): in Modo, Half is
purple and black mixed half and half, never lighter than the purple. Prints each cube's colour in both, read from the
pixels the purple covers in Modo's render.  Usage: check_group_mask_material.py <runtime>"""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))
from check_fresnel import pixels  # noqa: E402  (sets the plugin's modules up without Modo)
from moonray_modo import native  # noqa: E402

folder = root / ('test-results/group-mask-material' + (sys.argv[2] if len(sys.argv) > 2 else ''))
runtime = Path(sys.argv[1])
modo = folder / 'modo.Final Color Output.0001.exr'
output = folder / 'moonray.exr'
done = subprocess.run([str(runtime / 'moonray.exe'), '-in', str(folder / 'group_mask_material.rdla'), '-out', str(output),
                       '-exec_mode', 'scalar'], env=native.environment(runtime), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
if done.returncode or not output.is_file():
    raise SystemExit(done.stdout.decode(errors='replace')[-3000:])
subprocess.run([str(runtime / 'oiiotool.exe'), str(modo), '--ch', 'R,G,B', str(output), '--ch', 'R,G,B', '--mosaic', '1x2',
                '--colorconvert', 'linear', 'sRGB', '-o', str(folder / 'pair.png')], env=native.environment(runtime), check=True)


modo_picture, moonray_picture = pixels(runtime, modo), pixels(runtime, output)
width, height, _ = modo_picture
for name, (x0, x1) in (('Half', (0, width // 3)), ('Noise', (width // 3, 2 * width // 3)), ('Full', (2 * width // 3, width))):
    for label, (w, h, values) in (('Modo', modo_picture), ('MoonRay', moonray_picture)):
        # The upper middle of the third: the cube's front face.
        xs = range(x0 + (x1 - x0) * 2 // 5, x0 + (x1 - x0) * 3 // 5)
        ys = range(h * 2 // 5, h * 3 // 5)
        total = [0.0, 0.0, 0.0]
        for y in ys:
            for x in xs:
                for c in range(3):
                    total[c] += values[(y * w + x) * 3 + c]
        n = len(xs) * len(ys)
        print('%-6s %-8s %s' % (name, label, ' '.join('%.4f' % (v / n) for v in total)))
print('pair:', folder / 'pair.png')
