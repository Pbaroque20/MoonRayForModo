"""Native Windows renderer discovery and subprocess configuration."""
import os
import json
import tempfile
from pathlib import Path


def find_runtime(root):
    root = Path(root).expanduser()
    candidates = [root, root / 'bin']
    if root.name.lower() == 'moonray.exe':
        candidates.insert(0, root.parent)
    for directory in candidates:
        if (directory / 'moonray.exe').is_file():
            return directory.resolve()
    raise ValueError('Select the Windows MoonRay folder containing moonray.exe.')


def environment(directory):
    directory = Path(directory)
    env = dict(os.environ)
    # MoonRay's two-stage EXR writer consults TMPDIR (not Windows TEMP).
    env['TMPDIR'] = tempfile.gettempdir()
    env['REZ_MOONRAY_ROOT'] = str(directory.resolve())
    env['PATH'] = str(directory) + os.pathsep + env.get('PATH', '')
    dsos = [directory / 'rdl2dso', directory.parent / 'rdl2dso', directory.parent / 'lib' / 'rdl2dso', directory]
    env['RDL2_DSO_PATH'] = os.pathsep.join(str(p) for p in dsos if p.is_dir())
    # Toon materials lit by their smooth normals, not cut into steps along a coarse mesh's faces: read by MoonRay as it
    # starts (a runtime without the patch ignores it).
    env['MOONRAY_MODO_TOON_TERMINATOR'] = '1' if toon_terminator() else '0'
    # And a clean albedo of toon materials for the denoiser's guide (toon_albedo).
    env['MOONRAY_MODO_TOON_ALBEDO'] = '1' if toon_albedo() else '0'
    # The denoiser (denoise.exe, started with this environment too) cleans its guides first (denoise_clean_guides).
    env['MOONRAY_MODO_DENOISE_CLEAN_GUIDES'] = '1' if denoise_clean_guides() else '0'
    # And fog in Cryptomatte, with what lies behind it covered only as much as shows through (crypto_volumes).
    env['MOONRAY_MODO_CRYPTO_VOLUMES'] = '1' if crypto_volumes() else '0'
    # The fog in front of a see-through surface in alpha (fog_alpha), and each Cryptomatte sample counted once
    # (crypto_once).
    env['MOONRAY_MODO_FOG_ALPHA'] = '1' if fog_alpha() else '0'
    env['MOONRAY_MODO_CRYPTO_ONCE'] = '1' if crypto_once() else '0'
    # The four overrides of tools/port_source_switches.py, each read by MoonRay as it starts.
    env['MOONRAY_MODO_USD_SPECULAR'] = '1' if usd_specular() else '0'
    env['MOONRAY_MODO_OPAQUE_ALPHA'] = '1' if opaque_alpha() else '0'
    env['MOONRAY_MODO_TRANSMISSION_ROUGHNESS'] = '1' if transmission_roughness() else '0'
    env['MOONRAY_MODO_AUTO_XPU'] = '1' if auto_xpu() else '0'
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
    threads = render_threads(threads)
    if threads > 0:
        args += ['-threads', str(threads)]
    return args


def low_latency():
    """Whether renders leave Modo room to work (on by default): MoonRay runs below Modo's priority, and, where it is to
    take all the processor, one thread is left over. Measured with a stand-in for Modo's own work beside a render on
    12 threads: as before, it got 93 of its 600 frames in ten seconds, one in twenty over 120 ms late; with MoonRay
    below normal priority, 597, one in twenty at most 11 ms."""
    return _switch('low_latency', 'MOONRAY_MODO_LOW_LATENCY')


def render_threads(threads):
    """The threads MoonRay is told to use: as set, or all but one (low_latency) where it is to take all of them."""
    threads = int(threads)
    if threads > 0 or not low_latency():
        return threads
    cores = os.cpu_count() or 1
    return cores - 1 if cores > 4 else 0


def lower_priority(pid):
    """A renderer the plugin started, below normal priority (low_latency), so that Modo comes first: a render then uses
    what the processor has to spare. Windows only; True where it was lowered."""
    if os.name != 'nt' or not pid or not low_latency():
        return False
    try:
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x0200, False, int(pid))   # PROCESS_SET_INFORMATION
        if not handle:
            return False
        try:
            return bool(kernel.SetPriorityClass(handle, 0x4000))   # BELOW_NORMAL_PRIORITY_CLASS
        finally:
            kernel.CloseHandle(handle)
    except (OSError, AttributeError, ValueError):
        return False


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


def _gpu():
    try:
        from . import hardware
        return hardware.gpu()
    except Exception:return ''


def _cpu():
    try:
        from . import hardware
        return hardware.cpu()
    except Exception:return ''


def execution_status(log):
    """Read selection and fallback in log order; preparation is not GPU confirmation."""
    result=None
    for line in log.splitlines():
        line=line.lower()
        if 'executing a scalar render' in line: result='Scalar active (%s)'%(_cpu() or 'CPU')
        elif 'executing a vectorized render' in line: result='Vector active (%s)'%(_cpu()+' / AVX' if _cpu() else 'CPU / AVX')
        elif 'executing an xpu render' in line: result='XPU initializing'
        # With what it is running on, where the machine says: the first NVIDIA card and the processor.
        if 'gpu: setup complete' in line: result='XPU active (%s + %s)'%(_gpu() or 'NVIDIA GPU',_cpu() or 'CPU')
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
def _switch(key, variable):
    """One of MoonRay's preferences in Modo that MoonRay reads as it starts, on by default. Outside Modo, from its
    environment variable as it stands, on when that is not set."""
    try:
        from PySide2 import QtCore
    except ImportError:
        return os.environ.get(variable, '1') == '1'
    value = QtCore.QSettings('MoonRayForModo', settings_name()).value(key, True)
    return str(value).lower() in ('true', '1')


def toon_terminator():
    """Whether toon materials are lit by their smooth normals on coarse meshes."""
    return _switch('toon_terminator', 'MOONRAY_MODO_TOON_TERMINATOR')


def light_motion():
    """Whether a light that moves during the shutter is blurred: MoonRay moves one only when its own mb switch is on,
    which it leaves off, and the plugin then sets it (MoonLightIPR follows the same choice)."""
    return _switch('light_motion', 'MOONRAY_MODO_LIGHT_MOTION')


def toon_albedo():
    """Whether MoonRay's albedo output gives a toon material its own colour: the denoiser's guide, which is otherwise
    full of bright specks on toon surfaces, and the denoised picture as noisy as the render."""
    return _switch('toon_albedo', 'MOONRAY_MODO_TOON_ALBEDO')


def denoise_clean_guides():
    """Whether Open Image Denoise cleans the albedo and normal guides first and trusts them (cleanAux), in the
    denoiser of MoonRay's runtime (tools/port_denoise_overrides.py). MoonRay's own uses them as rendered and trusts
    them less, leaving more of the render's noise on textured, bumpy and see-through surfaces."""
    return _switch('denoise_clean_guides', 'MOONRAY_MODO_DENOISE_CLEAN_GUIDES')


def crypto_volumes():
    """Whether fog has mattes of its own in MoonRay's Cryptomatte, and what lies behind it is covered only as much
    as shows through. MoonRay's own leaves fog out, and covers what lies behind it whole."""
    return _switch('crypto_volumes', 'MOONRAY_MODO_CRYPTO_VOLUMES')


def fog_alpha():
    """Whether fog in front of a partly see-through surface is in the picture's alpha. MoonRay's own leaves it out
    there, so that fog in front of a pane against the sky is less opaque than it looks."""
    return _switch('fog_alpha', 'MOONRAY_MODO_FOG_ALPHA')


def crypto_once():
    """Whether each Cryptomatte sample is counted once in MoonRay's vector and XPU modes, where MoonRay's own now
    and then counts a pixel's surface twice."""
    return _switch('crypto_once', 'MOONRAY_MODO_CRYPTO_ONCE')


def usd_specular():
    """Whether a UsdPreviewSurface material in the specular workflow reflects its specular colour; MoonRay's own gives
    that workflow no highlight at all."""
    return _switch('usd_specular', 'MOONRAY_MODO_USD_SPECULAR')


def opaque_alpha():
    """Whether an image with no alpha channel reads as opaque in a texture's alpha; MoonRay's own reads it as 0."""
    return _switch('opaque_alpha', 'MOONRAY_MODO_OPAQUE_ALPHA')


def transmission_roughness():
    """Whether a Dwa material's independent transmission roughness is kept when its surface is mirror smooth;
    MoonRay's own then makes the transmission mirror sharp as well."""
    return _switch('transmission_roughness', 'MOONRAY_MODO_TRANSMISSION_ROUGHNESS')


def auto_xpu():
    """Whether MoonRay's Auto execution mode starts with XPU, falling back where the scene needs what XPU lacks;
    MoonRay's own starts Auto in vector mode."""
    return _switch('auto_xpu', 'MOONRAY_MODO_AUTO_XPU')


def source_switches():
    """The MoonRay Source Overrides MoonRay reads as it starts: a session started with others is started again."""
    return (toon_terminator(), toon_albedo(), crypto_volumes(), fog_alpha(), crypto_once()) + tuple(
        globals()[key]() for key in ('usd_specular', 'opaque_alpha', 'transmission_roughness', 'auto_xpu'))


def binary_geometry():
    """Whether scenes are handed to MoonRay with their geometry's heavy lists as binary (rdlb.py), on by default:
    much quicker to load, the same picture."""
    return _switch('binary_geometry', 'MOONRAY_MODO_BINARY_GEOMETRY')


def drain_tiles():
    """Whether a render stopped by hand, or by Smart Render, finishes the tiles MoonRay's workers are on and ends there
    as a finished frame (the plugin's change to MoonRay, tools/port_drain.py). Off, it is stopped as MoonRay's own stop
    does: at once, the picture kept as it stands, dark or coarse where tiles were being worked on."""
    return _switch('drain_tiles', 'MOONRAY_MODO_DRAIN')


def settings_name():
    """Where the preview's settings are kept. A test copy of Modo is given a name of its own, so that what a test
    sets (its runtime above all) is never what the user's own Modo reads while the test runs."""
    import os
    return os.environ.get('MOONRAY_MODO_PREFERENCES') or 'NativePreview'


def supports_pixel_filters(directory):
    """Whether this runtime's MoonRay has the Gaussian, Triangle and Blackman-Harris pixel filters."""
    import json
    try:return bool(json.loads((Path(directory)/'modo-session.json').read_text(encoding='utf-8')).get('pixel_filters'))
    except (OSError,ValueError,TypeError,AttributeError):return False

def display_filter_classes(directory):
    """The display filters this runtime's MoonRay has: each is a plugin of its own, and an older runtime has one or none."""
    from . import entities
    return sorted(name for name in entities.classes('displayfilter') if (Path(directory)/(name+'.so')).is_file())

def supports_bump_step(directory):
    """Whether this runtime's texture plugin reads a tiled bump image as finely as it is tiled (its bump_step)."""
    import json
    try:return bool(json.loads((Path(directory)/'modo-session.json').read_text(encoding='utf-8')).get('bump_step'))
    except (OSError,ValueError,TypeError,AttributeError):return False

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
