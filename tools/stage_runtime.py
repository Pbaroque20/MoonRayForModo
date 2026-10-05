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
# Fail packaging rather than ship examples whose constructors cannot load.
for name in ('SphereGeometry.dll','SphereGeometry.so.proxy','BoxGeometry.dll','BoxGeometry.so.proxy'):
    if not (build/'bin'/name).is_file():
        raise ValueError('Rebuild the MoonShine geometry library before staging: '+name)
pending = [build / 'bin/moonray.exe']
if (build/'bin/modo_rdl_import.exe').is_file(): pending.append(build/'bin/modo_rdl_import.exe')
if (build/'bin/modo_display_stream.exe').is_file(): pending.append(build/'bin/modo_display_stream.exe')
if (build/'bin/denoise.exe').is_file(): pending.append(build/'bin/denoise.exe')
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
# OIDN's Windows module loader requests this unprefixed basename even in
# MinGW builds; keep the imported lib-prefixed binary and a loader alias.
oidn_cpu = tools/'libOpenImageDenoise_device_cpu.dll'
if oidn_cpu.is_file():
    alias='OpenImageDenoise_device_cpu.dll'
    shutil.copy2(oidn_cpu,destination/alias)
    manifest[alias.lower()]={'source':str(oidn_cpu),'sha256':hashlib.sha256(oidn_cpu.read_bytes()).hexdigest()}
if args.xpu:
    assets={'shaders/OptixGPUPrograms.ptx':build/'shaders/OptixGPUPrograms.ptx',
        'licenses/CUDA.txt':root/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/LICENSE',
        'licenses/OptiX.txt':root/'toolchain/xpu/optix-dev/LICENSE.txt'}
    for name,source in assets.items():
        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        manifest[name]={'source':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
# Capability is tied to the staged executable, so a mismatched runtime cannot hang
# waiting for a protocol it does not implement. This is packaging, not a render test.
executable=destination/'moonray.exe'
if b'MOONRAY_MODO_SESSION' in executable.read_bytes():
    capability=destination/'modo-session.json'
    capability.write_text(json.dumps({'protocol':1,'scene_memory':True,'command_memory':True,'progressive_preview':b'Modo native progressive preview' in executable.read_bytes(),'executable_sha256':hashlib.sha256(executable.read_bytes()).hexdigest()},indent=2),encoding='utf-8')
    manifest['modo-session.json']={'source':str(capability),'sha256':hashlib.sha256(capability.read_bytes()).hexdigest()}
# Pair-array support is tied to both the instancer DSO and geometry library.
instancer=destination/'RdlInstancerGeometry.dll'
if instancer.is_file() and b'xform_list_close' in instancer.read_bytes():
    capability=destination/'modo-instance-motion.json'
    hashes={name:hashlib.sha256((destination/name).read_bytes()).hexdigest()
            for name in ('RdlInstancerGeometry.dll','librendering_geom.dll')}
    capability.write_text(json.dumps({'version':1,'sha256':hashes},indent=2),encoding='utf-8')
    manifest[capability.name]={'source':str(capability),'sha256':hashlib.sha256(capability.read_bytes()).hexdigest()}
# Category support requires matching scene schema, scalar/vector accumulation,
# and film/output libraries. Marker does not claim render validation.
crypto_libs=('libscene_rdl2.dll','librendering_rndr.dll','moonray.exe')
if all((destination/n).is_file() for n in crypto_libs) and b'Modo surface category: 0 primary deep ID' in (destination/crypto_libs[0]).read_bytes() and b'Cryptomatte category unavailable' in (destination/crypto_libs[1]).read_bytes():
    capability=destination/'modo-crypto-categories.json'
    hashes={n:hashlib.sha256((destination/n).read_bytes()).hexdigest() for n in crypto_libs}
    capability.write_text(json.dumps({'version':1,'surface_categories':['object','material','asset'],'volume_coverage':False,'render_validated':False,'sha256':hashes},indent=2),encoding='utf-8')
    manifest[capability.name]={'source':str(capability),'sha256':hashlib.sha256(capability.read_bytes()).hexdigest()}
(destination / 'build-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print('Staged', len(manifest), 'native binaries in', destination)
