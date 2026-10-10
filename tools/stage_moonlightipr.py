"""Copy the built MoonLightIPR session, its device program and the CUDA runtime into one folder."""
import argparse
import pathlib
import shutil

root = pathlib.Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--destination', default=str(root / 'build/moonlightipr/stage'))
args = parser.parse_args()
build = root / 'build/moonlightipr'
xpu = root / 'toolchain/xpu'
destination = pathlib.Path(args.destination).resolve()
assets = {'moonlightipr_session.exe': build / 'bin/moonlightipr_session.exe',
          'MoonLightIPRKernel.ptx': build / 'shaders/MoonLightIPRKernel.ptx',
          # MoonLightIPR's own licence, and what it is and is not to MoonRay and DreamWorks.
          'licenses/MoonLightIPR.txt': root / 'moonlightipr/LICENSE', 'licenses/MoonLightIPR-NOTICE.md': root / 'moonlightipr/NOTICE.md',
          'licenses/CUDA.txt': xpu / 'cuda_cudart-windows-x86_64-12.8.90-archive/LICENSE',
          'licenses/OptiX.txt': xpu / 'optix-dev/LICENSE.txt'}
for library in (xpu / 'cuda_cudart-windows-x86_64-12.8.90-archive/bin').glob('cudart64_*.dll'):
    assets[library.name] = library
missing = [str(source) for source in assets.values() if not source.is_file()]
if missing or not any(name.startswith('cudart64_') for name in assets):
    raise SystemExit('Build MoonLightIPR first (tools/build_moonlightipr.py); missing: ' + ', '.join(missing or ['cudart64_*.dll']))
for name, source in assets.items():
    target = destination / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
print('Staged MoonLightIPR:', destination)
