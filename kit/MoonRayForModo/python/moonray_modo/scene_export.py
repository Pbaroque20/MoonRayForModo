"""The Modo scene written as MoonRay reads it, to render with moonray.exe or on a farm (export), as Convert LXO to RDL
and the kit's bin/lxo2rdl.exe write scenes through scripts/export_moonray.py in Modo's command-line engine. Up to 0.5.5
Export as MoonRay Scene wrote the open scene with it on Modo's own thread; Convert LXO to RDL took its place.

The choices:
- RDLA: one text file, which MoonRay reads and a person can read too.
- RDLB: one binary file: smaller (about a third), quicker to load, the same picture.
- RDLA + RDLB: MoonRay's split scene, its settings as text and its geometry binary; MoonRay is given both.
- Render outputs: the scene's AOVs, Cryptomatte and deep output beside the beauty, or the beauty alone.
- Collect textures: every picture the scene reads copied into a folder beside it, named from the scene, the scene
  pointing to them there (paths relative to the scene's folder: render from that folder).
- Every frame of the frame range: one scene for each frame, numbered, as Render Animation would render them.
The geometry's heavy lists are written as binary as the scene is written (write_binary, as Rhizome's export does);
one RDLB or one RDLA is made of the two by MoonRay's own converter (rdl2_convert), through a temporary folder."""
import hashlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

FORMATS = (('rdla', 'RDLA: one text file'), ('rdlb', 'RDLB: one binary file (smaller, quicker to load)'),
           ('split', 'RDLA + RDLB: settings as text, geometry binary (MoonRay\'s split scene)'))
# What a scene names that is a file to collect.
COLLECTED = {'.tx', '.exr', '.hdr', '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.tga', '.bmp', '.vdb', '.pfm', '.cube', '.ies'}
STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')


def converter(runtime):
    """MoonRay's scene converter, beside the runtime's libraries."""
    found = Path(runtime) / 'rdl2_convert.exe'
    if not found.is_file():
        raise ValueError('RDLB needs MoonRay\'s converter, rdl2_convert.exe, in the runtime: reinstall the kit, or export RDLA.')
    return found


def unescaped(text):
    return re.sub(r'\\(.)', lambda match: match.group(1), text)


def collect_textures(text, scene_path):
    """Copy every file the scene text names into <scene>_textures beside it, and point the text there by a path
    relative to the scene's folder. Returns the text and how many files were copied."""
    folder = scene_path.with_name(scene_path.stem + '_textures')
    copied = {}

    def placed(source):
        if source not in copied:
            folder.mkdir(exist_ok=True)
            # Pictures of the same name from different folders are kept apart by a short mark of where they were.
            mark = hashlib.sha1(str(source.parent).encode('utf-8')).hexdigest()[:6]
            target = folder / ('%s_%s' % (mark, source.name))
            if not target.exists():
                shutil.copyfile(str(source), str(target))
            copied[source] = target
        return copied[source]

    def replace(match):
        value = unescaped(match.group(1))
        if Path(value.replace('<UDIM>', '1001')).suffix.lower() not in COLLECTED:
            return match.group(0)
        if '<UDIM>' in value:
            pattern = Path(value)
            tiles = sorted(pattern.parent.glob(pattern.name.replace('<UDIM>', '[0-9][0-9][0-9][0-9]'))) if pattern.parent.is_dir() else []
            if not tiles:
                return match.group(0)
            for tile in tiles:
                placed(tile)
            first = copied[tiles[0]]
            name = first.name[:7] + pattern.name
            return '"%s/%s"' % (folder.name, name)
        source = Path(value)
        if not source.is_file():
            return match.group(0)
        return '"%s/%s"' % (folder.name, placed(source).name)
    return STRING.sub(replace, text), len(copied)


# A line of MoonRay's converter holding one string: an attribute (["name"] = "value",) or a metadata entry
# ({"name", "type", "value"},), the value written as it is, from its first quote to its last.
RAW_STRING = re.compile(r'^(\s*(?:\["[^"\\]*"\] = |\{"[^"\\]*", "[^"\\]*", ))"(.*)"(\}?,?)$')


def escaped(path):
    """MoonRay's converter writes the strings of a split scene's RDLA as they are, unescaped: a Windows path's
    backslashes and the quotes inside Cryptomatte's manifest then break MoonRay's reading of it. They are escaped
    again, as the plugin's own RDLA has them."""
    lines = path.read_text(encoding='utf-8').split('\n')
    for index, line in enumerate(lines):
        match = RAW_STRING.match(line)
        if match and ('"' in match.group(2) or '\\' in match.group(2)):
            lines[index] = '%s"%s"%s' % (match.group(1), match.group(2).replace('\\', '\\\\').replace('"', '\\"'), match.group(3))
    path.write_text('\n'.join(lines), encoding='utf-8')


def write(text, target, kind, runtime):
    """The scene text written as the format asked for; returns the files written."""
    target = Path(target)
    if kind == 'rdla':
        written = target.with_suffix('.rdla')
        written.write_text(text, encoding='utf-8')
        return [written]
    # The converter reads the scene text from a file: one in a temporary folder of its own, so nothing but the
    # scene asked for appears beside it.
    folder = Path(tempfile.mkdtemp(prefix='moonray-export-'))
    source = folder / (target.stem + '.rdla')
    source.write_text(text, encoding='utf-8')
    try:
        from . import native
        output = target.with_suffix('.rdlb') if kind == 'rdlb' else target.with_suffix('')
        done = subprocess.run([str(converter(runtime)), '-d', str(runtime), '-i', str(source), '-o', str(output)],
                              env=native.environment(Path(runtime)), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if done.returncode:
            raise ValueError('MoonRay could not convert the scene: ' + done.stdout.decode(errors='replace')[-600:])
        if kind == 'rdlb':
            return [output]
        escaped(output.with_suffix(".rdla"))
        return [output.with_suffix('.rdla'), output.with_suffix('.rdlb')]
    finally:
        shutil.rmtree(str(folder), ignore_errors=True)


def write_binary(text, payload, target, kind, runtime):
    """The scene as written with its geometry's heavy lists collected as binary (rdlb.collecting, as Rhizome's export_job
    writes it): RDLA + RDLB as they are; one RDLB made of the two by MoonRay's converter, which reads the binary lists at
    once. Formatting every point as text, then reading it all back to make RDLB, took minutes on a heavy scene (a car's
    RDLB 82 s to 16 s; Rhizome's export of another, 5.5 min to 15 s). One RDLA is not made here (export). Returns the
    files written."""
    target = Path(target)
    if kind == 'split':
        held = target.with_suffix('.rdla'), target.with_suffix('.rdlb')
        held[0].write_text(text, encoding='utf-8')
        held[1].write_bytes(payload)
        return list(held)
    folder = Path(tempfile.mkdtemp(prefix='moonray-export-'))
    try:
        light, heavy = folder / (target.stem + '.rdla'), folder / (target.stem + '.rdlb')
        light.write_text(text, encoding='utf-8')
        heavy.write_bytes(payload)
        from . import native
        output = target.with_suffix('.rdlb' if kind == 'rdlb' else '.rdla')
        done = subprocess.run([str(converter(runtime)), '-d', str(runtime), '-i', str(light), '-i', str(heavy), '-o', str(output)],
                              env=native.environment(Path(runtime)), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if done.returncode:
            raise ValueError('MoonRay could not convert the scene: ' + done.stdout.decode(errors='replace')[-600:])
        if kind == 'rdla':
            # The converter writes strings as they are (escaped).
            escaped(output)
        return [output]
    finally:
        shutil.rmtree(str(folder), ignore_errors=True)


def export(choices, warnings):
    """Write the scene (or each frame of the range) as chosen; returns the files written."""
    import lx
    import modo
    from . import host, native, rdla
    from .scene_setup import configure, values as scene_values
    from .preferences import Preferences
    runtime = native.find_runtime(Preferences().get('runtime') or native.default_runtime())
    held = scene_values()
    scene = modo.Scene()
    path = Path(choices['path'])
    if path.suffix.lower() not in ('.rdla', '.rdlb', ''):
        path = path.with_suffix('.rdla')
    selection = lx.service.Selection()
    now = selection.GetTime()
    fps = float(scene.fps)
    if choices['frames']:
        render = scene.renderItem
        first, last = int(round(float(render.channel('first').get()))), int(round(float(render.channel('last').get())))
        frames = [(frame, path.with_name('%s.%04d%s' % (path.stem, frame, path.suffix or '.rdla'))) for frame in range(first, last + 1)]
    else:
        frames = [(None, path)]
    written = []
    try:
        for frame, target in frames:
            if frame is not None:
                selection.SetTime(frame / fps)
            # Motion blur where the render settings or the camera rendered through at this frame ask for it, as a render.
            if held.get('final_motion') or host.camera_motion_blur(scene):
                from .animation import capture_current
                snapshot = capture_current(held['surface'] == 2)
            else:
                # A whole reading the Scene cache kept for this frame (the preview's, scene_reading), where the scene has
                # no unsaved changes, as Rhizome's export takes it; else read from Modo, and kept for the next.
                from . import scene_reading
                evaluated = held['surface'] == 2
                held_key = scene_reading.key(evaluated)
                snapshot = scene_reading.load(held_key)
                if snapshot is None:
                    snapshot = host.snapshot(evaluated_geometry=evaluated)
                    if held_key is not None:
                        scene_reading.keep(held_key, scene_reading.freeze(snapshot), snapshot)
                snapshot.pop('_full_capture', None)
                snapshot.pop('_evaluated_data', None)
            configure(snapshot, held)
            if not choices['outputs']:
                snapshot['custom_aovs'] = []
                snapshot.pop('deep', None)
            arguments = (snapshot, snapshot['width'], snapshot['height'], held['samples'], held['environment'],
                         str(target.with_suffix('.exr')))
            # For RDLB and RDLA + RDLB, the geometry's heavy lists collected as binary as the scene is written
            # (write_binary), where the kit writes binary geometry (native.binary_geometry, on unless switched off): a car
            # as RDLB 82 s to 16 s, as RDLA + RDLB 8 s. RDLA, all text, is written here as before: MoonRay's converter
            # writes the lists as text slower than the kit does (41 s to 120 s).
            payload = None
            if native.binary_geometry() and choices['format'] in ('rdlb', 'split'):
                from . import rdlb
                with rdlb.collecting(fingerprints=False) as sink:
                    text = rdla.scene_text(*arguments)
                payload = sink.payload() if sink.objects else None
            else:
                text = rdla.scene_text(*arguments)
            if choices['collect']:
                text, count = collect_textures(text, target)
            written += (write_binary(text, payload, target, choices['format'], runtime) if payload is not None
                        else write(text, target, choices['format'], runtime))
            warnings.extend(w for w in snapshot.get('warnings', []) if w not in warnings)
    finally:
        selection.SetTime(now)
    return written
