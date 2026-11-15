"""How many texels across each texture a scene can show, by the meshes it is on as the camera sees them: for XPU2's texture
overflow mode, which steps a texture down to what its meshes need on screen before it compresses anything or makes
every texture smaller (host_texture.h). A 4K picture on a mesh 80 pixels wide on screen needs a few hundred texels; one
filling the frame keeps its size.

A texture's need is the most any mesh wearing it asks: the mesh's width on screen at its nearest placement
(moonlightipr_detail.edge_pixels), over how many repeats of the texture lie across it (its UVs' span, times the scale
its map and any UV placement before it give), with room for a closer look (MARGIN). Worked out from the scene text as
written: a texture reaches a mesh through the maps bound into the materials its parts are assigned (rdla), so nothing
of how each kind of map is written needs knowing here but its texture's path, its "scale" and the "uv_affine" of a
placement it reads its UVs through.
"""
import math
import re

# Texels a pixel of the mesh's width on screen is given: a mesh seen closer in a reflection, at a slant, or a little
# nearer than its nearest placement keeps its detail.
MARGIN = 2.0
# Never less than this a side (XPU2's own smallest overflow side).
SMALLEST = 256

_BLOCK = re.compile(r'(?m)^(?:local [A-Za-z_]\w* = |\w+\[[^\]]*\] = )?([A-Z][A-Za-z0-9_]*)\(("(?:[^"\\]|\\.)*")\) \{')
_REFERENCE = re.compile(r'\b[A-Z][A-Za-z0-9_]*\(("(?:[^"\\]|\\.)*")\)')
_TABLE = re.compile(r'(?m)^(materials|displacements)\[("(?:[^"\\]|\\.)*")\] = ')
_TEXTURE = re.compile(r'"([^"]*\.tx)"')
_SCALE = re.compile(r'\["scale"\] = Vec2\(([^,]+),\s*([^)]+)\)')
_AFFINE = re.compile(r'\["uv_affine"\] = Vec4\(([^,]+),\s*([^,]+),\s*([^,]+),\s*([^)]+)\)')


def _unquote(text):
    return text[1:-1].replace('\\\\', '\\').replace('\\"', '"')


def blocks(text):
    """{object's name: its text}, each object the scene text defines, a definition's body to its closing brace."""
    found = {}
    starts = list(_BLOCK.finditer(text))
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        found[_unquote(match.group(2))] = text[match.end():end]
    return found


def _number(text):
    try:
        value = float(text)
        return value if math.isfinite(value) else 1.0
    except ValueError:
        return 1.0


_ALIAS = re.compile(r'(?:materials|displacements)\[("(?:[^"\\]|\\.)*")\]\s*$')
_COORDINATES = re.compile(r'\["input_texture_coordinates"\] = bind\([A-Z][A-Za-z0-9_]*\(("(?:[^"\\]|\\.)*")\)')


def _affine(body):
    """How much a placement's uv_affine stretches the UVs (its columns' larger length), 1 where it has none."""
    found = _AFFINE.search(body)
    if not found:
        return 1.0
    a, b, c, d = (_number(found.group(k)) for k in range(1, 5))
    return max(math.hypot(a, c), math.hypot(b, d), 1e-6)


def repeats(name, held):
    """How many times an object's texture lies across one unit of UV: its scale's larger, times its own placement's and
    that of each placement (uv_affine) it reads its coordinates through (input_texture_coordinates)."""
    body = held.get(name, '')
    found = 1.0
    scale = _SCALE.search(body)
    if scale:
        found *= max(abs(_number(scale.group(1))), abs(_number(scale.group(2))), 1e-6)
    found *= _affine(body)
    seen = {name}
    coordinates = _COORDINATES.search(body)
    while coordinates:
        other = _unquote(coordinates.group(1))
        if other in seen or other not in held:
            break
        seen.add(other)
        found *= _affine(held[other])
        coordinates = _COORDINATES.search(held[other])
    return found


def textures_of(text):
    """{material tag: {texture path: repeats across one unit of UV}}: each texture a material reaches through what is
    bound into it, its displacement's included; a texture used at several repeats, its fewest (the most it is
    stretched, which asks for the most texels)."""
    held = blocks(text)
    roots, aliases = {}, {}
    for match in _TABLE.finditer(text):
        tag = _unquote(match.group(2))
        line = text[match.end():text.find('\n', match.end())]
        named = _REFERENCE.search(line)
        if named:
            roots.setdefault(tag, set()).add(_unquote(named.group(1)))
        alias = _ALIAS.match(line)
        if alias:
            aliases.setdefault(tag, set()).add(_unquote(alias.group(1)))
    # A tag that is another's (materials["a"] = materials["b"]): what that one reaches, followed to its end.
    for tag in list(aliases):
        pending, seen = list(aliases[tag]), {tag}
        while pending:
            other = pending.pop()
            if other in seen:
                continue
            seen.add(other)
            roots.setdefault(tag, set()).update(roots.get(other, ()))
            pending.extend(aliases.get(other, ()))
    result = {}
    for tag, names in roots.items():
        found = {}
        pending, seen = list(names), set()
        while pending:
            name = pending.pop()
            if name in seen or name not in held:
                continue
            seen.add(name)
            body = held[name]
            for path in _TEXTURE.findall(body):
                path = path.replace('\\\\', '\\')
                repeat = repeats(name, held)
                found[path] = min(found[path], repeat) if path in found else repeat
            pending.extend(_unquote(r) for r in _REFERENCE.findall(body))
        if found:
            result[tag] = found
    return result


def uv_span(mesh):
    """The larger side of the box the mesh's UVs fill (its first map's, as rdla writes them), at least a little."""
    from .rows import numbers
    uvs = mesh.get('uvs')
    if uvs is None or not len(uvs):
        return 1.0
    flat = numbers(uvs, 2)
    flat = flat if flat is not None else [c for uv in uvs for c in uv]
    if len(flat) < 4:
        return 1.0
    us, vs = flat[0::2], flat[1::2]
    span = max(max(us) - min(us), max(vs) - min(vs))
    return span if span > 1e-6 and math.isfinite(span) else 1.0


# At most this many frames of an animation are looked at for its textures' needs, spread evenly over it, its first and
# last among them.
FRAME_SAMPLES = 120


def frame_placements(snapshot, first, last, fps, step=1):
    """Where the camera and each mesh's item stand at frames of an animation (Modo's main thread: world matrices at
    their times), for needs() to take each texture's most over the whole shot: {'read': {item: matrix at the snapshot's
    reading}, 'frames': [{'camera': matrix, item: matrix}, ...]}. None where Modo cannot be asked."""
    try:
        import modo
        from .host import world_matrix
        document = modo.Scene()
        frames = list(range(int(first), int(last) + 1, max(1, int(step))))
        if len(frames) > FRAME_SAMPLES:
            picked = sorted({frames[round(i * (len(frames) - 1) / (FRAME_SAMPLES - 1))] for i in range(FRAME_SAMPLES)})
            frames = picked
        camera = document.item(snapshot['camera']['identity'])
        items = {}
        for mesh in snapshot.get('meshes') or []:
            identity = mesh.get('source_item') or str(mesh.get('identity', '')).split('|')[0]
            if identity and identity not in items:
                try:
                    items[identity] = document.item(identity)
                except Exception:
                    pass
        read_time = float(snapshot.get('frame', first)) / float(fps)
        held = {'read': {identity: world_matrix(item, read_time) for identity, item in items.items()}, 'frames': []}
        for frame in frames:
            time = frame / float(fps)
            at = {'camera': world_matrix(camera, time)}
            at.update({identity: world_matrix(item, time) for identity, item in items.items()})
            held['frames'].append(at)
        return held
    except Exception:
        return None


def _times(a, b):
    """Two 4x4 matrices (rows, as the kit keeps them: a point times the matrix) multiplied."""
    return [sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4)) for r in range(4) for c in range(4)]


def needs(text, placed, camera, width, placements=None):
    """{texture path: texels across it the scene can show}, from the scene text and placed: (mesh, its material tags)
    as rdla wrote each mesh. With placements (frame_placements, an animation's), the most over all its frames: each mesh
    moved as its item moves from where it was read, the camera to where it stands, so that every frame of a shot is
    given the same needs and XPU2 fits its textures once (a texture fitted to each frame's camera would change size
    from one frame to the next). Textures no mesh wears (a light's, the environment's) are left out: XPU2 steps them
    down as before."""
    by_tag = textures_of(text)
    if placements and placements.get('frames'):
        from .coordinates import inverse
        result = {}
        moved = {}
        for at in placements['frames']:
            views = []
            for mesh, tags in placed:
                identity = mesh.get('source_item') or str(mesh.get('identity', '')).split('|')[0]
                read, now = placements['read'].get(identity), at.get(identity)
                if read is not None and now is not None and read != now:
                    key = (id(mesh), identity)
                    if key not in moved:
                        moved[key] = _times(mesh.get('matrix') or [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], inverse(read))
                    mesh = dict(mesh, matrix=_times(moved[key], now))
                views.append((mesh, tags))
            for path, side in _needs(by_tag, views, dict(camera, matrix=at['camera']), width).items():
                result[path] = max(result.get(path, 0), side)
        return result
    return _needs(by_tag, placed, camera, width)


def _needs(by_tag, placed, camera, width):
    """needs() for one view, its textures already followed to their materials (textures_of)."""
    from .moonlightipr_detail import edge_pixels
    result = {}
    for mesh, tags in placed:
        wanted = [by_tag[tag] for tag in tags if tag in by_tag]
        if not wanted:
            continue
        try:
            _, across = edge_pixels(mesh, camera, width, across=True)
        except Exception:
            continue
        if not (across > 0 and math.isfinite(across)):
            continue
        span = uv_span(mesh)
        for found in wanted:
            for path, repeat in found.items():
                texels = MARGIN * across / max(1e-6, span * repeat)
                side = SMALLEST
                while side < texels and side < 65536:
                    side *= 2
                result[path] = max(result.get(path, 0), side)
    return result


def user_data(need):
    """The scene text's lines that hand XPU2 the needs (host_texture.h textureNeeds): paths and sides."""
    if not need:
        return []
    from .rdla import string
    paths = sorted(need)
    return ['UserData("/modo/xpu2/texture_density") {', '  ["string_key"] = "xpu2_texture_paths",',
            '  ["string_values"] = {%s},' % ', '.join(string(p) for p in paths), '  ["int_key"] = "xpu2_texture_sides",',
            '  ["int_values"] = {%s},' % ', '.join(str(int(need[p])) for p in paths), '}']
