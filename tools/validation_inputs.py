"""Content fingerprints used by deferred render checks and release packaging."""
import hashlib
from pathlib import Path


def sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()


def fingerprint(root, runtime):
    root,runtime=Path(root),Path(runtime)
    sources={}
    for directory in ('kit/MoonRayForModo','native-port'):
        for path in sorted((root/directory).rglob('*')):
            if path.is_file() and path.suffix.lower() in ('.py','.cfg','.json','.cc','.cpp','.h','.hpp','.ispc','.isph','.cmake','.txt','.lx') and '__pycache__' not in path.parts and path.name!='MoonRayPreview.lx':
                sources[path.relative_to(root).as_posix()]=sha256(path)
    for name in ('geometry_bridge.cpp','render_cache.cpp'):
        path=root/'native-modo'/name
        sources[path.relative_to(root).as_posix()]=sha256(path)
    for name in ('validation_inputs.py','validate_cpu_feature_renders.py'):
        path=root/'tools'/name
        sources[path.relative_to(root).as_posix()]=sha256(path)
    binaries={path.name:sha256(path) for path in sorted(runtime.iterdir())
              if path.is_file() and path.suffix.lower() in ('.exe','.dll','.so','.proxy')}
    if 'moonray.exe' not in binaries:
        raise ValueError('Runtime fingerprint requires moonray.exe')
    return {'schema':1,'sources':sources,'binaries':binaries}


def require_feature_reports(root, runtime):
    import json
    current=fingerprint(root,runtime)
    for feature in ('materials','textures','geometry','environments','rendering'):
        path=Path(root)/'test-results/cpu-features'/feature/'render-report.json'
        if not path.is_file():
            raise ValueError('Missing deferred render validation: '+feature)
        report=json.loads(path.read_text(encoding='utf-8'))
        if report.get('passed') is not True or report.get('inputs')!=current:
            raise ValueError('Render validation is failed or stale for '+feature+'. Validate the current source and runtime before packaging.')
    return current
