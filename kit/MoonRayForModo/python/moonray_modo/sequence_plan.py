"""Plan sequence recovery without replacing existing render files."""
import json,shutil
from pathlib import Path
from .denoising import held_sidecar,sidecar as denoised_copy

def valid_exr(path):
    path=Path(path)
    if not path.is_file() or path.stat().st_size<32:return False
    with path.open('rb') as stream:return stream.read(4)==b'\x76\x2f\x31\x01'

# How many digits a frame's number has where nothing says otherwise: what every sequence had before the window asked.
DIGITS=6

def frame_name(prefix,frame,digits=DIGITS,extension='exr'):
    """A frame's file: frame.0001.exr, its number filled out with zeros to so many digits."""
    return '%s.%0*d.%s'%(prefix,digits,frame,extension)

def let_go(path):
    """What a frame saved only as a picture was made from, gone once the picture is written: its EXR, its denoised copy
    and what was kept to denoise it. The EXR last: until it goes the frame reads as not yet finished."""
    path=Path(path)
    if denoised_copy(path).exists():denoised_copy(path).unlink()
    shutil.rmtree(str(path.with_name(path.name+'.postprocess')),ignore_errors=True)
    if path.exists():path.unlink()

def manifest_path(directory,prefix):
    """A sequence's record, named for its prefix: a folder holds as many sequences as it has prefixes."""
    return Path(directory)/(prefix+'.moonray-sequence.json')

def held_manifest(directory,prefix):
    """The record this prefix's sequence has in a folder, or None. Before each had its own there was one to a folder,
    which went for its own prefix alone: with another prefix in the folder, Sequence exists stopped the render."""
    own=manifest_path(directory,prefix)
    if own.exists():return own
    older=Path(directory)/'moonray-sequence.json'
    try:
        if older.exists() and json.loads(older.read_text(encoding='utf-8')).get('prefix','frame')==prefix:return older
    except (OSError,ValueError,AttributeError):pass
    return None

def window_values(held,scene):
    """What the Render Animation window opens with, from the scene's own (scene: first, last, step, fps, motion) and what
    it was last rendered with (held, as kept with the scene). The folder, prefix and digits stay. The frames, rate and
    motion blur stay while the scene's own are what they were then, and follow the scene's own once those change."""
    held=held if isinstance(held,dict) else {}
    values=dict(scene,folder='',prefix='frame',digits=DIGITS,engine='moonray')
    values.update({key:held[key] for key in ('folder','prefix','digits','engine') if key in held})
    if held.get('scene')==scene:values.update({key:held[key] for key in scene if key in held})
    return values

def plan(directory,first,last,step,prefix,fps,motion,missing=False,denoise=False,signature=None,digits=DIGITS,picture=None,notices=None):
    """The frames to render, and those already there. Without Render missing frames, a sequence of this prefix already in
    the folder is refused, so that nothing is overwritten unasked. With it, every frame of the range that is already
    there is kept and passed over, and only the others are rendered: the range, the step, the scene and its settings may
    have changed since (a sequence taken further, or finished after an edit), which notices (a list, where given) is
    told. Nothing already there is ever overwritten; an EXR in the way that is not one is refused.
    picture: the type (image_formats) a sequence is saved in alone, its EXRs let go of as each frame is done; a frame is
    done when its picture is there."""
    from .assets import file_hash
    from .image_formats import find
    said=notices if notices is not None else []
    saved={}
    directory=Path(directory);manifest=held_manifest(directory,prefix)
    if manifest is not None:
        if not missing:raise ValueError('A sequence named %s is already in this folder. Choose another file prefix, or enable Render missing frames to continue it.'%prefix)
        try:saved=json.loads(manifest.read_text(encoding='utf-8'))
        except (OSError,ValueError):saved={}
        if signature is not None and saved.get('signature') not in (None,signature):
            said.append('The scene or its settings changed since the frames already there were rendered; they are kept as they are.')
        # A sequence is in one picture type: its frames' names and what is let go of follow it.
        if 'picture' in saved and saved['picture']!=picture:raise ValueError('Sequence picture type differs from the frames already there; choose the same type, or another file prefix.')
        # And in one count of digits, which its frames' names are written with.
        if saved.get('digits',DIGITS)!=digits:raise ValueError('Sequence frame digits differ from the frames already there (%d); choose the same, or another file prefix.'%saved.get('digits',DIGITS))
        for key,words in (('fps','frame rate'),('motion_blur','motion blur')):
            value={'fps':fps,'motion_blur':motion}[key]
            if key in saved and saved[key]!=value:said.append('The %s differs from the frames already there.'%words)
    recorded={v.get('frame'):v for v in saved.get('frames',[]) if isinstance(v,dict)}
    pending=[];completed=[]
    for frame in range(first,last+1,step):
        path=directory/frame_name(prefix,frame,digits);sidecar=held_sidecar(path)
        if picture:
            shown=directory/frame_name(prefix,frame,digits,find(picture)[2])
            if shown.exists():
                if not missing:raise ValueError('Output exists for frame %d. Enable Render missing frames to keep it and render the others.'%frame)
                completed.append(dict(recorded.get(frame,{}),frame=frame,file=str(shown.resolve()),sha256=file_hash(shown),reused=True))
            # An EXR in the way is only this sequence's own (let go of once its picture is written) where its record says so.
            elif (path.exists() or sidecar.exists()) and not (missing and saved):raise ValueError('Output exists for frame %d: an EXR this sequence has no record of. Move it aside, or choose another file prefix.'%frame)
            else:pending.append(frame)
            continue
        if path.exists():
            if not missing:raise ValueError('Output exists for frame %d. Enable Render missing frames to keep it and render the others.'%frame)
            if not valid_exr(path):raise ValueError('Existing frame is not a recognizable EXR; move it aside before recovery: '+str(path))
            entry=recorded.get(frame,{})
            if denoise and not sidecar.exists():
                # Rendered, its denoised copy not made yet: made from what was kept for it, else rendered again.
                if not (path.with_name(path.name+'.postprocess')/'manifest.json').is_file():
                    said.append('Frame %d has no denoised copy and nothing kept to make one: it is kept as it is.'%frame)
                    completed.append(dict(entry,frame=frame,file=str(path.resolve()),sha256=file_hash(path),reused=True))
                    continue
                pending.append(frame);continue
            if denoise and not valid_exr(sidecar):raise ValueError('Denoised frame is not a recognizable EXR; move it aside before recovery: '+str(sidecar))
            completed.append(dict(entry,frame=frame,file=str(path.resolve()),sha256=file_hash(path),reused=True,**({'denoised_sha256':file_hash(sidecar)} if denoise else {})))
        else:
            if sidecar.exists():raise ValueError('Orphan denoised output exists: '+str(sidecar))
            pending.append(frame)
    return pending,completed

def earlier_frames(directory,prefix,first,last,step):
    """What the sequence's record holds of frames outside this range (a sequence taken further, or a part of it rendered
    again), kept in its record beside the frames of this one."""
    manifest=held_manifest(directory,prefix)
    if manifest is None:return []
    try:frames=json.loads(manifest.read_text(encoding='utf-8')).get('frames',[])
    except (OSError,ValueError,AttributeError):return []
    wanted=set(range(first,last+1,step))
    return [v for v in frames if isinstance(v,dict) and v.get('frame') not in wanted]
