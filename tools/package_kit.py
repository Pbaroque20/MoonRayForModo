"""Package the Modo kit, optionally with the validated native AVX renderer."""
import hashlib
import json
import pathlib
import sys
import zipfile
import uuid

root = pathlib.Path(__file__).resolve().parents[1]
with_runtime = '--with-runtime' in sys.argv
runtime = root / 'runtime/native-avx'
if with_runtime:
    from validation_inputs import require_feature_reports, fingerprint
    try:
        verified_inputs=require_feature_reports(root,runtime)
    except (ValueError,OSError) as exc:
        raise SystemExit(str(exc))
    validation = json.loads((runtime / 'validated-render.json').read_text(encoding='utf-8'))
    if validation['executable_sha256'] != hashlib.sha256((runtime / 'moonray.exe').read_bytes()).hexdigest():
        raise SystemExit('Validate the current renderer before packaging it.')
destination = root / 'dist' / ('MoonRayForModo-0.1.0-native-avx.zip' if with_runtime
                               else 'MoonRayForModo-0.1.0-prototype.zip')
destination.parent.mkdir(exist_ok=True)
manifest = {}
staged=destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.tmp')
try:
    with zipfile.ZipFile(staged, 'w', zipfile.ZIP_DEFLATED) as archive:
        def add(path, name):
            name = str(name).replace('\\','/')
            data = pathlib.Path(path).read_bytes()
            info = zipfile.ZipInfo(name, (2020,1,1,0,0,0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info,data)
            manifest[name] = {'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}

        for path in sorted((root / 'kit/MoonRayForModo').rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc' and path.name!='MoonRayPreview.lx':
                add(path, str(path.relative_to(root / 'kit')))
        for name in ('README.md', 'LICENSE', 'THIRD_PARTY.md'):
            add(root / name, 'MoonRayForModo/' + name)
        add(root / 'docs/AVX_BUILD.md', 'MoonRayForModo/docs/AVX_BUILD.md')
        add(root / 'patches/configurable-x86-isa.patch', 'MoonRayForModo/patches/configurable-x86-isa.patch')
        if with_runtime:
            for path in sorted(runtime.iterdir()):
                if path.is_file():
                    add(path, 'MoonRayForModo/runtime/native-avx/' + path.name)
            for path in sorted((root / 'patches/native-windows').iterdir()):
                if path.is_file():
                    add(path, 'MoonRayForModo/patches/native-windows/' + path.name)
        info = zipfile.ZipInfo('MoonRayForModo/package-manifest.json',(2020,1,1,0,0,0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        archive.writestr(info,json.dumps({'files':manifest,'new_features':'unverified'},sort_keys=True,indent=2).encode())
    if with_runtime and fingerprint(root,runtime)!=verified_inputs:
        staged.unlink()
        raise SystemExit('Source/runtime changed during packaging; previous package was preserved.')
    staged.replace(destination)
finally:
    if staged.exists():
        staged.unlink()
print(destination)
