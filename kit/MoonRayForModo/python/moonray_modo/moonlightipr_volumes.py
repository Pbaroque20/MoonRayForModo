"""VDB volumes for the MoonLightIPR preview.

MoonRay reads a VDB file itself. MoonLightIPR has no VDB reader, so the runtime's modo_vdb_grid turns the density grid
into a plain block of numbers once, no larger than GRID_CELLS along an edge, which the session loads as a 3D picture.
The fog is then a unit cube, put where the grid's own transform and the item's put it, that is as thick at each
place as the grid says.
"""
import hashlib
import struct
import subprocess
from pathlib import Path

# The most cells along an edge of what the preview holds; a finer grid is read at this fineness.
GRID_CELLS = 192
UNIT_CUBE = ([[x, y, z] for x in (0.0, 1.0) for y in (0.0, 1.0) for z in (0.0, 1.0)],
             [[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]])


def dense(path, grid, runtime, colours=False):
    """The grid of a VDB file as a file the session reads: (file, the transform from the unit cube to the grid's own
    space). Made once for a file as it stands and kept."""
    from . import native
    from .moonlightipr_materials import cache_folder
    source = Path(path)
    stat = source.stat()
    runtime = Path(runtime) if runtime else native.default_runtime()
    digest = hashlib.sha256(repr((str(source.resolve()), stat.st_size, stat.st_mtime_ns, grid, GRID_CELLS, 'moonlightipr-vdb-v2')).encode()).hexdigest()
    target = cache_folder() / (digest + '.mlv')
    if not target.is_file() or not target.stat().st_size:
        tool = runtime / 'modo_vdb_grid.exe'
        if not tool.is_file():
            raise OSError('this runtime has no VDB reader for the preview (modo_vdb_grid.exe)')
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_suffix('.part')
        done = subprocess.run([str(tool), str(source), grid or '', str(GRID_CELLS), str(staged)], env=native.environment(runtime),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=600)
        if done.returncode or not staged.is_file():
            raise ValueError(done.stdout.decode(errors='replace').strip()[-300:] or 'the VDB file could not be read')
        staged.replace(target)
    with target.open('rb') as held:
        head = held.read(84)
    if len(head) < 84 or head[:4] != (b'MLV4' if colours else b'MLV1'):
        if head[:4] in (b'MLV1', b'MLV4'):
            raise ValueError('grid %s holds %s, where %s are needed' % (grid, 'single numbers' if head[:4] == b'MLV1' else 'colours', 'colours' if colours else 'single numbers'))
        raise ValueError('the grid made from the VDB file is not valid')
    return str(target), list(struct.unpack_from('<16f', head, 20))


def product(a, b):
    """Two transforms one after the other, basis vectors in rows as Modo and MoonRay hold them."""
    return [sum(a[row * 4 + k] * b[k * 4 + column] for k in range(4)) for row in range(4) for column in range(4)]


def fogs(scene, runtime, warnings):
    """The VDB volumes of a scene as MoonLightIPR draws them: [(mesh, material tag, material)]. Each mesh is the unit
    cube placed over the grid; its material says what the fog stops, scatters and which way."""
    from .entities import inverse_rows
    from .working_space import color as working_color
    made = []
    for entry in scene.get('extra_geometry', []):
        if entry.get('kind') != 'vdb':
            continue
        name = entry.get('name', 'Volume')
        try:
            file, unit = dense(entry['file'], entry.get('density_grid', 'density'), runtime)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            warnings.append('MoonLightIPR does not show volume %s (%s).' % (name, exc))
            continue
        placed = [float(v) for v in (entry.get('matrix') or [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])]
        world = product(unit, placed)
        # The light the fog gives off, from its emission grid, which has a box of its own.
        glow, glow_rows, given = None, None, max(0.0, float(entry.get('emission', 1)))
        if entry.get('emission_grid') and given > 0:
            try:
                glow, glow_unit = dense(entry['file'], entry['emission_grid'], runtime, True)
                glow_rows = [v for row in inverse_rows(product(glow_unit, placed)) for v in row]
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                warnings.append('MoonLightIPR shows volume %s without the light its emission grid gives off (%s).' % (name, exc))
        tag = '|vdb|' + str(entry.get('identity', name))
        gain = max(0.0, float(entry.get('density', 1)))
        material = {'color': [0.0, 0.0, 0.0], 'roughness': 1.0, 'metallic': 0, '_volume': {
            'extinction': [gain] * 3, 'albedo': working_color([float(v) for v in entry.get('volume_color', [1, 1, 1])]), 'emission': [given if glow else 0.0] * 3,
            'anisotropy': float(entry.get('anisotropy', 0)), 'grid': file, 'rows': [v for row in inverse_rows(world) for v in row],
            'glow': glow, 'glow_rows': glow_rows}}
        mesh = {'name': name, 'identity': tag, 'vertices': UNIT_CUBE[0], 'faces': UNIT_CUBE[1], 'matrix': world, 'material': tag, 'smooth': False}
        made.append((mesh, tag, material))
    return made
