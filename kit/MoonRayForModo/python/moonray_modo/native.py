"""Native Windows renderer discovery and subprocess configuration."""
import os
import json
import tempfile
from pathlib import Path


def find_runtime(root):
    root = Path(root).expanduser()
    candidates = [root, root / 'blender.shared', root / 'bin']
    if root.name.lower() == 'moonray.exe':
        candidates.insert(0, root.parent)
    for directory in candidates:
        if (directory / 'moonray.exe').is_file():
            return directory.resolve()
    raise ValueError('Select the Windows MoonRay folder containing moonray.exe or blender.shared.')


def environment(directory):
    directory = Path(directory)
    env = dict(os.environ)
    # MoonRay's two-stage EXR writer consults TMPDIR (not Windows TEMP).
    env['TMPDIR'] = tempfile.gettempdir()
    env['REZ_MOONRAY_ROOT'] = str(directory.resolve())
    env['PATH'] = str(directory) + os.pathsep + env.get('PATH', '')
    dsos = [directory / 'rdl2dso', directory.parent / 'rdl2dso', directory.parent / 'lib' / 'rdl2dso', directory]
    env['RDL2_DSO_PATH'] = os.pathsep.join(str(p) for p in dsos if p.is_dir())
    # A child process must not load Modo's Python/Qt libraries into MoonRay.
    for key in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'MOONRAY_MODO_SESSION', 'MOONRAY_MODO_GENERATION', 'MOONRAY_MODO_COMMAND'):
        env.pop(key, None)
    return env


def arguments(scene, output, threads=0, mode='vectorized'):
    if mode not in ('scalar', 'vector', 'vectorized', 'xpu', 'auto'):
        raise ValueError('Unsupported execution mode')
    args = ['-in', str(Path(scene).resolve()), '-out', str(Path(output).resolve()),
            '-exec_mode', mode]
    args.append('-info')
    if int(threads) > 0:
        args += ['-threads', str(int(threads))]
    return args


def default_runtime():
    supplied = os.environ.get('MOONRAY_MODO_RUNTIME', '')
    if supplied:
        return supplied
    installed_config = Path(__file__).resolve().parents[2] / 'runtime.json'
    if installed_config.is_file():
        try:
            return str(find_runtime(json.loads(installed_config.read_text(encoding='utf-8'))['directory']))
        except (OSError, ValueError, KeyError, TypeError):
            pass
    # Source checkout layout and conventional adjacent runtime folder.
    here = Path(__file__).resolve()
    for parent in here.parents:
        for candidate in (parent / 'runtime/native-avx', parent / 'runtime', parent / 'MoonRayRuntime'):
            try:
                return str(find_runtime(candidate))
            except ValueError:
                pass
    return ''


def installation_id():
    path=Path(__file__).resolve().parents[2]/'runtime.json'
    try:
        return json.loads(path.read_text(encoding='utf-8')).get('installation_id','')
    except (OSError,ValueError,TypeError,AttributeError):
        return ''


def supports_xpu(directory):
    directory=Path(directory)
    return (directory/'shaders/OptixGPUPrograms.ptx').is_file() and any(directory.glob('cudart64_*.dll'))


def default_execution_mode(directory):
    return 'auto'


def execution_status(log):
    """Read selection and fallback in log order; preparation is not GPU confirmation."""
    result=None
    for line in log.splitlines():
        line=line.lower()
        if 'executing a scalar render' in line: result='Scalar active (CPU)'
        elif 'executing a vectorized render' in line: result='Vector active (CPU / AVX)'
        elif 'executing an xpu render' in line: result='XPU initializing'
        if 'gpu: setup complete' in line: result='XPU active (NVIDIA GPU + CPU)'
        if 'falling back to cpu' in line: result='Vector active (CPU fallback — see Render Log)'
    return result


def supports_paired_instance_motion(directory):
    """Trust only the exact geometry binaries recorded by runtime staging."""
    root=Path(directory).resolve()
    try:
        signature=tuple((p.stat().st_size,p.stat().st_mtime_ns) for p in
                        (root/'modo-instance-motion.json',root/'RdlInstancerGeometry.dll',root/'librendering_geom.dll'))
    except OSError:return False
    return _paired_instance_capability(str(root),signature)


from functools import lru_cache
@lru_cache(maxsize=8)
def _paired_instance_capability(directory,signature):
    import hashlib
    root=Path(directory)
    try:
        data=json.loads((root/'modo-instance-motion.json').read_text(encoding='utf-8'))
        if data.get('version')!=1:return False
        for name in ('RdlInstancerGeometry.dll','librendering_geom.dll'):
            if hashlib.sha256((root/name).read_bytes()).hexdigest()!=data['sha256'][name]:return False
        return True
    except (OSError,ValueError,KeyError,TypeError):return False


def configured_runtime(settings):
    """Apply installed-runtime changes even when importing before opening Preview."""
    stamp = installation_id()
    if stamp and settings.value('runtime_installation') != stamp:
        settings.setValue('previous_runtime', settings.value('runtime', ''))
        settings.setValue('runtime', default_runtime())
        settings.setValue('runtime_installation', stamp)
    return find_runtime(str(settings.value('runtime', default_runtime())))


_CRYPTO_LIBS=('libscene_rdl2.dll','librendering_rndr.dll','moonray.exe')
def supports_crypto_categories(directory):
    root=Path(directory).resolve()
    try:signature=tuple((p.stat().st_size,p.stat().st_mtime_ns) for p in [root/'modo-crypto-categories.json']+[root/n for n in _CRYPTO_LIBS])
    except OSError:return False
    return _crypto_capability(str(root),signature)

@lru_cache(maxsize=8)
def _crypto_capability(directory,signature):
    import hashlib
    root=Path(directory)
    try:
        data=json.loads((root/'modo-crypto-categories.json').read_text(encoding='utf-8'))
        return data.get('version')==1 and all(hashlib.sha256((root/n).read_bytes()).hexdigest()==data['sha256'][n] for n in _CRYPTO_LIBS)
    except (OSError,ValueError,KeyError,TypeError):return False
