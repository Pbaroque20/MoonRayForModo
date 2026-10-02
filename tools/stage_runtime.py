"""Bundle only the new native build and its resolved native DLL dependencies."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import argparse

root = Path(__file__).resolve().parents[1]
build = root / 'build/native-renderer-avx'
tools = root / 'toolchain/msys64/ucrt64/bin'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--destination', type=Path, default=root / 'runtime/native-avx')
parser.add_argument('--xpu',action='store_true')
args=parser.parse_args()
destination = args.destination.resolve()
cache=(build/'CMakeCache.txt').read_text(encoding='utf-8')
built_xpu='MOONRAY_USE_OPTIX:BOOL=ON' in cache
if args.xpu!=built_xpu: raise ValueError('Staging mode must match the renderer build (--xpu for an XPU build)')
if args.xpu and destination==(root/'runtime/native-avx').resolve(): raise ValueError('Use a separate XPU runtime destination')
if not (build / 'bin/moonray.exe').is_file():
    raise SystemExit('The native renderer has not been built yet.')
search = [build / 'bin', build / 'log4cplus/bin', tools]
if args.xpu: search.append(root/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/bin')
available = {path.name.lower(): path for directory in reversed(search)
             for path in directory.iterdir() if path.is_file()}
destination.mkdir(parents=True, exist_ok=True)
manifest_path = destination / 'build-manifest.json'
previous = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.is_file() else {}
# Re-staging must never preserve a validation marker from an older binary.
validation = destination / 'validated-render.json'
if validation.exists():
    validation.unlink()
pending = [build / 'bin/moonray.exe']
pending.append(tools / 'maketx.exe')
pending.append(tools / 'oiiotool.exe')
pending += [path for path in (build / 'bin').iterdir()
            if path.suffix.lower() in ('.dll', '.so', '.proxy')]
pending += list(tools.glob('*OpenImageDenoise*cpu*.dll'))
# Preserve and revalidate the previously resolved dependency closure. Unchanged
# imports need not be inspected by launching objdump again for every DLL.
pending += [Path(entry['source']) for entry in previous.values() if Path(entry['source']).is_file() and Path(entry['source']).suffix.lower() in ('.exe','.dll','.so','.proxy')]
manifest = {}
system = Path(os.environ['SystemRoot']) / 'System32'
while pending:
    source = pending.pop()
    key = source.name.lower()
    if key in manifest:
        continue
    target = destination / source.name
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    old = previous.get(key, {})
    if old.get('source') == str(source) and old.get('sha256') == digest and target.is_file():
        if hashlib.sha256(target.read_bytes()).hexdigest() == digest:
            manifest[key] = old
            continue
    shutil.copy2(source, target)
    manifest[key] = {'source': str(source), 'sha256': digest}
    output = subprocess.check_output([str(tools / 'objdump.exe'), '-p', str(source)],
        text=True, errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
    for name in re.findall(r'DLL Name:\s*(\S+)', output):
        dependency = available.get(name.lower())
        if dependency:
            pending.append(dependency)
        elif name.lower().startswith(('api-ms-win-', 'ext-ms-win-')) or (system / name).is_file():
            continue
        else:
            raise RuntimeError('Missing native DLL dependency: ' + name + ' required by ' + source.name)
if args.xpu:
    assets={'shaders/OptixGPUPrograms.ptx':build/'shaders/OptixGPUPrograms.ptx',
        'licenses/CUDA.txt':root/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/LICENSE',
        'licenses/OptiX.txt':root/'toolchain/xpu/optix-dev/LICENSE.txt'}
    for name,source in assets.items():
        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        manifest[name]={'source':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
(destination / 'build-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print('Staged', len(manifest), 'native binaries in', destination)
