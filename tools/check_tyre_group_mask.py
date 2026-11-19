"""Render the tyre's Group Mask scene as the plugin exported it (tools/probe_cl_tyre_group_mask.py) with MoonRay, and
set Modo's render above MoonRay's in one picture (pair.png): purple where the mask image is white, the tread's own
material where it is black, blended along the mask's soft edges in Modo, with no light rim.
Usage: check_tyre_group_mask.py <runtime> [exec mode, vectorized by default] [folder in test-results]"""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))
from check_fresnel import pixels  # noqa: F401,E402  (sets the plugin's modules up without Modo)
from moonray_modo import native  # noqa: E402

folder = root / 'test-results' / (sys.argv[3] if len(sys.argv) > 3 else 'tyre-group-mask')
runtime = Path(sys.argv[1])
mode = sys.argv[2] if len(sys.argv) > 2 else 'vectorized'
modo = folder / 'modo.RAW.0001.exr'
output = folder / ('moonray-%s.exr' % mode)
done = subprocess.run([str(runtime / 'moonray.exe'), '-in', str(folder / 'tyre_group_mask.rdla'), '-out', str(output),
                       '-exec_mode', mode], env=native.environment(runtime), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
if done.returncode or not output.is_file():
    raise SystemExit(done.stdout.decode(errors='replace')[-3000:])
subprocess.run([str(runtime / 'oiiotool.exe'), str(modo), '--ch', 'R,G,B', str(output), '--ch', 'R,G,B', '--mosaic', '1x2',
                '--colorconvert', 'linear', 'sRGB', '-o', str(folder / ('pair-%s.png' % mode))], env=native.environment(runtime), check=True)
print('pair:', folder / ('pair-%s.png' % mode))
