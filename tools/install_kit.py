"""Install the development kit into Modo's verified user:Kits startup path."""
from datetime import datetime
from pathlib import Path
import hashlib
import json
import os
import shutil
import argparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--custom-view-only', action='store_true',
                    help='Install the verified Qt CustomView kit without the experimental native adapter.')
args = parser.parse_args()

root = Path(__file__).resolve().parents[1]
source = root / 'kit/MoonRayForModo'
destination = Path(os.environ['APPDATA']) / 'Luxology/Kits/MoonRayForModo'
runtime = root / 'runtime/native-avx'
from validation_inputs import require_feature_reports
try:
    require_feature_reports(root,runtime)
except (ValueError,OSError) as exc:
    raise SystemExit(str(exc))
converter = root / 'toolchain/msys64/ucrt64/bin/maketx.exe'
adapter=source/'bin/MoonRayPreview.lx'
if args.custom_view_only:
    report = json.loads((root/'test-results/custom-view/report.json').read_text())
    profile = root/'test-results/gui-custom-opengl'
    process = json.loads((profile/'process-result.json').read_text())
    if not (report.get('passed') and report.get('valid_gl') and report.get('disposed')
            and report.get('bright_pixels', 0) > 100 and process.get('clean_shutdown')
            and process.get('pid') == report.get('pid')):
        raise SystemExit('CustomView requires a visible rendered framebuffer and clean shutdown.')
    for path in source.rglob('*'):
        if path.is_file() and path.suffix in ('.py', '.cfg'):
            tested = profile/'Configs/MoonRayForModo'/path.relative_to(source)
            if not tested.is_file() or tested.read_bytes() != path.read_bytes():
                raise SystemExit('CustomView source changed since the GUI test: ' + str(path))
elif adapter.is_file():
    preview_report=root/'test-results/pview-kit/report.json'
    preview=json.loads(preview_report.read_text()) if preview_report.is_file() else {}
    if not (preview.get('passed') and preview.get('clean_shutdown') and
            preview.get('nonblack_pixels',0)>100 and preview.get('plugin_sha256')==hashlib.sha256(adapter.read_bytes()).hexdigest()):
        raise SystemExit('Native adapter installation requires a nonblack PView render and clean shutdown with this exact binary. The installed kit was not changed.')
if not (runtime / 'maketx.exe').is_file():
    raise SystemExit('Stage and validate maketx.exe with the runtime before installation.')
if not (runtime / 'moonray.exe').is_file():
    raise SystemExit('A validated native runtime must be staged before installing this kit.')
if not (runtime / 'validated-render.json').is_file():
    raise SystemExit('The native renderer has not yet passed a real render test.')
validation = json.loads((runtime / 'validated-render.json').read_text(encoding='utf-8'))
if validation.get('executable_sha256') != hashlib.sha256((runtime / 'moonray.exe').read_bytes()).hexdigest():
    raise SystemExit('The renderer has changed since its last successful render test.')
glass_report = root / 'test-results/glass/report.json'
if not glass_report.is_file():
    raise SystemExit('Run tools/validate_glass.py before installing the glass-capable kit.')
glass_validation = json.loads(glass_report.read_text(encoding='utf-8'))
for name in ('ModoGlassMaterial.so', 'ModoGlassMaterial.so.proxy'):
    if not (runtime / name).is_file() or glass_validation.get('binaries', {}).get(name) != hashlib.sha256((runtime/name).read_bytes()).hexdigest():
        raise SystemExit('The glass module has not passed validation: ' + name)
if not glass_validation.get('passed'):
    raise SystemExit('Glass render validation failed.')

for relative,key in [('surface-updates/report.json','shader_sha256'),('moonshine/report.json','binaries'),
                     ('specular/report.json','binaries')]:
    report=json.loads((root/'test-results'/relative).read_text(encoding='utf-8'))
    if not report.get('passed'):
        raise SystemExit('Shader render validation failed: '+relative)
    for name,digest in report[key].items():
        if hashlib.sha256((runtime/name).read_bytes()).hexdigest()!=digest:
            raise SystemExit('Shader changed since validation: '+name)

backup = None
if destination.exists():
    backup = root / 'backups' / ('installed-kit-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    shutil.copytree(destination, backup)
manifest = {'modo_executable': r'C:\Program Files\Modo16.1v9\modo\modo.exe',
            'runtime': str(runtime), 'backup': str(backup) if backup else None, 'files': {}}
for path in source.rglob('*'):
    if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
        continue
    relative = path.relative_to(source)
    if args.custom_view_only and 'bin' in relative.parts:
        continue
    installed = destination / relative
    installed.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, installed)
    manifest['files'][relative.as_posix()] = hashlib.sha256(installed.read_bytes()).hexdigest()
if args.custom_view_only:
    # The complete previous kit was backed up above. Remove only this known
    # experimental adapter so Modo cannot auto-register the broken PView route.
    installed_adapter = destination/'bin/MoonRayPreview.lx'
    if installed_adapter.is_file():
        installed_adapter.unlink()
(destination / 'runtime.json').write_text(json.dumps({'directory': str(runtime)}, indent=2), encoding='utf-8')
(root / 'test-results/kit-install.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print('Installed:', destination)
