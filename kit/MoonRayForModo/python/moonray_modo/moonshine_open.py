"""MoonRay > Open Scene as MoonShine...: a Modo scene (.lxo) opened with its Shader Tree's images in MoonShine graphs from
the start, so that they never enter Modo's memory. The scene is the same afterwards as opened as usual and moved with
Move Shader Tree Textures to MoonShine Graphs: the same graphs, their nodes tagged the same way, so that that command
brings them up to date later.

How: the scene's file is read here, without Modo (an IFF file: a FORM of chunks, each item an ITEM chunk of
sub-chunks). Each image clip's file (its 'filename' string channel) is noted, and a copy of the scene is written to the
kit's cache in which each clip names a one-pixel stand-in image of its own instead; other files the scene names by a
path relative to its folder are named by their full path in the copy, so that it reads them from where they are. The
copy is opened, and the command moves the layers into graphs, reading each stand-in as the image it stands for
(shader_tree_scene.PLACEHOLDERS). A clip the command does not take out (a layer that stays in the Shader Tree, an
environment's image) is given its own file again, and so loads the image as it would have. The user's file is never
written; the opened scene is the copy, and is saved with Save As where it is to go.

The reading and writing of the file are here with no Modo (read_clips, stand_in_copy); open() is Modo's side."""
import hashlib
import os
import struct
import zlib
from pathlib import Path

# One pixel, mid grey: what each stand-in clip loads.
STAND_IN = (b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR' + struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
            + struct.pack('>I', zlib.crc32(b'IHDR' + struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)) & 0xffffffff))
_DATA = zlib.compress(b'\x00\x80\x80\x80')
STAND_IN += struct.pack('>I', len(_DATA)) + b'IDAT' + _DATA + struct.pack('>I', zlib.crc32(b'IDAT' + _DATA) & 0xffffffff)
STAND_IN += struct.pack('>I', 0) + b'IEND' + struct.pack('>I', zlib.crc32(b'IEND') & 0xffffffff)
# Image clip item types whose file this reads and stands in for.
CLIP_TYPES = ('videoStill',)


class Unreadable(ValueError):
    """A file this reader cannot follow: the scene is then opened as it is."""


def chunks(data, start, end, size_bytes=4):
    """(id, body start, body end) of the IFF chunks between start and end (sizes of size_bytes, bodies padded to even)."""
    at = start
    while at + 4 + size_bytes <= end:
        kind = data[at:at + 4]
        size = struct.unpack('>I' if size_bytes == 4 else '>H', data[at + 4:at + 4 + size_bytes])[0]
        body = at + 4 + size_bytes
        if body + size > end:
            raise Unreadable('a chunk runs past its end')
        yield kind, body, body + size
        at = body + size + (size & 1)


def _string(data, at):
    """A null-ended string at at, and where what follows it starts (strings are padded to even)."""
    end = data.index(b'\0', at)
    text = data[at:end].decode('utf-8', 'replace')
    after = end + 1
    if (after - at) & 1:
        after += 1
    return text, after


def item_header(data, start):
    """(type, name, reference number, where its sub-chunks start) of an ITEM chunk's body."""
    kind, at = _string(data, start)
    name, at = _string(data, at)
    number = struct.unpack('>I', data[at:at + 4])[0]
    return kind, name, number, at + 4


def form(data):
    if data[:4] != b'FORM' or data[8:12] not in (b'LXOB', b'LXOO', b'LXO\x00'):
        raise Unreadable('not a Modo scene')
    return 12, min(len(data), 8 + struct.unpack('>I', data[4:8])[0])


def read_clips(data):
    """The scene's image clips: [{'number', 'name', 'filename', 'colorspace', 'format', 'type'}] as the file holds them
    (a file name as it is written: relative to the scene's folder, or whole)."""
    start, end = form(data)
    found = []
    for kind, body, stop in chunks(data, start, end):
        if kind != b'ITEM':
            continue
        item_type, name, number, at = item_header(data, body)
        if item_type not in CLIP_TYPES:
            continue
        clip = {'number': number, 'type': item_type, 'name': name}
        for sub, sub_body, sub_end in chunks(data, at, stop, 2):
            if sub == b'CHNS':
                key, after = _string(data, sub_body)
                value = data[after:sub_end].split(b'\0', 1)[0].decode('utf-8', 'replace')
                if key in ('filename', 'colorspace', 'format'):
                    clip[key] = value
            elif sub == b'VNAM':
                clip['name'] = data[sub_body:sub_end].split(b'\0', 1)[0].decode('utf-8', 'replace')
        found.append(clip)
    return found


def whole(path_text, folder):
    """A path as the scene names it, whole. Modo writes a file under a folder the scene shares with it relative to that
    folder (images/a.png, or textures/a.png from a scene one folder down), and finds it by looking in the scene's folder
    and then in each folder above it: so it is found here."""
    if not path_text:
        return path_text
    path = Path(path_text)
    if path.is_absolute() or path.drive:
        return str(path)
    found = located(path, folder)
    return str(found if found is not None else (Path(folder) / path).resolve())


def located(path, folder):
    """Where a relative path is, from the scene's folder or a folder above it, or None."""
    here = Path(folder).resolve()
    for place in [here] + list(here.parents):
        try:
            candidate = place / path
            if candidate.is_file():
                return candidate.resolve()
        except (OSError, ValueError):
            return None
    return None


def _chns(key, value):
    body = key.encode('utf-8') + b'\0'
    if len(body) & 1:
        body += b'\0'
    body += value.encode('utf-8') + b'\0'
    if len(body) & 1:
        body += b'\0'
    return b'CHNS' + struct.pack('>H', len(body)) + body


def _relative_file(value, folder):
    """Where a string channel names a file by a path relative to the scene's folder (or one above it), and it is there:
    its whole path."""
    if not value or len(value) > 1024 or '\n' in value or not ('/' in value or '\\' in value or '.' in value):
        return None
    try:
        path = Path(value)
        if path.is_absolute() or path.drive:
            return None
        found = located(path, folder)
        return str(found) if found is not None else None
    except (OSError, ValueError):
        return None


def stand_in_copy(data, folder, stand_ins):
    """The scene's bytes with each image clip naming its own stand-in file (stand_ins(clip) -> path, or None to leave
    the clip as it is) and every other file named relative to the scene's folder named whole; and {stand-in path: the
    clip's own file, whole}."""
    start, end = form(data)
    out = [data[:12]]
    mapping = {}
    for kind, body, stop in chunks(data, start, end):
        if kind != b'ITEM':
            out.append(data[body - 8:stop] + (b'\0' if (stop - body) & 1 else b''))
            continue
        item_type, name, number, at = item_header(data, body)
        clip = None
        if item_type in CLIP_TYPES:
            held = {'number': number, 'type': item_type, 'name': name}
            for sub, sub_body, sub_end in chunks(data, at, stop, 2):
                if sub == b'CHNS':
                    key, after = _string(data, sub_body)
                    held[key] = data[after:sub_end].split(b'\0', 1)[0].decode('utf-8', 'replace')
                elif sub == b'VNAM':
                    held['name'] = data[sub_body:sub_end].split(b'\0', 1)[0].decode('utf-8', 'replace')
            stand_in = stand_ins(held) if held.get('filename') else None
            if stand_in:
                clip = (held, str(stand_in))
                mapping[str(stand_in)] = dict(held, filename=whole(held['filename'], folder))
        parts = [data[body:at]]
        for sub, sub_body, sub_end in chunks(data, at, stop, 2):
            raw = data[sub_body - 6:sub_end] + (b'\0' if (sub_end - sub_body) & 1 else b'')
            if sub == b'CHNS':
                key, after = _string(data, sub_body)
                value = data[after:sub_end].split(b'\0', 1)[0].decode('utf-8', 'replace')
                if clip is not None and key == 'filename':
                    raw = _chns(key, clip[1])
                elif clip is not None and key == 'format':
                    raw = _chns(key, 'PNG')
                else:
                    moved = _relative_file(value, folder)
                    if moved:
                        raw = _chns(key, moved)
            parts.append(raw)
        content = b''.join(parts)
        out.append(b'ITEM' + struct.pack('>I', len(content)) + content + (b'\0' if len(content) & 1 else b''))
    result = b''.join(out)
    return result[:4] + struct.pack('>I', len(result) - 8) + result[8:], mapping


def cache_folder(scene):
    from . import textures
    key = hashlib.sha256(os.path.normcase(str(Path(scene).resolve())).encode('utf-8')).hexdigest()[:16]
    return Path(textures.cache_root()) / 'MoonShine Scenes' / key


def prepare(scene):
    """Write the stand-in copy of a scene to the kit's cache: (the copy's path, {stand-in, folded case: the clip as
    the scene has it, its file whole}). Unreadable where the file cannot be followed."""
    scene = Path(scene).resolve()
    data = scene.read_bytes()
    folder = cache_folder(scene)
    images = folder / 'stand-ins'
    images.mkdir(parents=True, exist_ok=True)

    def stand_in(clip):
        # Named as the image it stands for, in a folder of its own: Modo names a clip it loads by its file's name.
        target = images / str(clip['number']) / (Path(clip['filename'].replace('\\', '/')).stem + '.png')
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file():
            target.write_bytes(STAND_IN)
        return target
    copy, mapping = stand_in_copy(data, scene.parent, stand_in)
    target = folder / scene.name
    target.write_bytes(copy)
    return target, {os.path.normcase(os.path.abspath(k)): v for k, v in mapping.items()}


def open_scene(path, progress=None):
    """Open a scene with its images in MoonShine graphs (the module's description): the stand-in copy opened, the
    command run, the clips it keeps given their own files again. progress: a shader_tree_dialog.Progress. Cancelled
    before the scene opens, nothing is left (the copy is taken away); cancelled while it is converted, the scene is left
    open as it would be opened as usual, every clip loading its own image. Returns the report's lines."""
    import shutil
    import lx
    from . import shader_tree_scene, shader_tree_dialog
    progress = progress or shader_tree_dialog.CURRENT
    step = progress.step if progress is not None else (lambda *args: None)
    try:
        step('Reading %s...' % Path(path).name, 0.0, 1.0)
        copy, mapping = prepare(path)
        step('Opening the scene without its images...', .03, 1.0)
    except shader_tree_dialog.Cancelled:
        try:
            shutil.rmtree(cache_folder(path))
        except OSError:
            pass
        lines = ['Cancelled: no scene was opened.']
        for line in lines:
            lx.out('MoonRay: ' + line)
        return lines
    except (Unreadable, OSError, ValueError, struct.error) as exc:
        lx.out('MoonRay: %s could not be read for Open Scene as MoonShine (%s); it is opened as it is.' % (path, exc))
        lx.eval('scene.open {%s} normal' % path)
        return ['Opened as it is: the file could not be read (%s).' % exc]
    shader_tree_scene.PLACEHOLDERS.clear()
    shader_tree_scene.PLACEHOLDERS.update(mapping)
    try:
        if progress is not None:
            # A scene half opened cannot be taken back: once it opens, its conversion is all that Cancel can stop.
            held, progress.cancellable = progress.cancellable, False
        lx.eval('scene.open {%s} normal' % copy)
        if progress is not None:
            progress.cancellable = held
            progress.base = (.1, .9)
        lx.eval('moonray.material.moveShaderTreeTextures')
        lines = list(shader_tree_scene.LAST_REPORT)
        if lines and lines[0].startswith('Cancelled'):
            # As opened as usual: every stand-in clip loads its own image again.
            import modo
            for clip in modo.Scene().items('videoStill'):
                held = shader_tree_scene.stood_in(clip)
                if held is not None:
                    lx.eval('item.channel videoStill$filename {%s} item:{%s}' % (held['filename'], clip.id))
            lines = ['Cancelled: the scene is open as it would be opened as usual, with its images in the Shader Tree.']
    finally:
        shader_tree_scene.PLACEHOLDERS.clear()
    lines.append('Opened from a copy of %s in %s: save it with Save As where it is to go (your file is not changed).' % (path, copy.parent))
    for line in lines:
        lx.out('MoonRay: ' + line)
    return lines
