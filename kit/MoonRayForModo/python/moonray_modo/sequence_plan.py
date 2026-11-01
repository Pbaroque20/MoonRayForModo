"""Plan sequence recovery without replacing existing render files."""
import json
from pathlib import Path

def valid_exr(path):
    path=Path(path)
    if not path.is_file() or path.stat().st_size<32:return False
    with path.open('rb') as stream:return stream.read(4)==b'\x76\x2f\x31\x01'

# How many digits a frame's number has where nothing says otherwise: what every sequence had before the window asked.
DIGITS=6

def frame_name(prefix,frame,digits=DIGITS):
    """A frame's file: frame.0001.exr, its number filled out with zeros to so many digits."""
    return '%s.%0*d.exr'%(prefix,digits,frame)

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
    values=dict(scene,folder='',prefix='frame',digits=DIGITS)
    values.update({key:held[key] for key in ('folder','prefix','digits') if key in held})
    if held.get('scene')==scene:values.update({key:held[key] for key in scene if key in held})
    return values

def plan(directory,first,last,step,prefix,fps,motion,missing=False,denoise=False,signature=None,digits=DIGITS):
    from .assets import file_hash
    saved={}
    directory=Path(directory);manifest=held_manifest(directory,prefix)
    if manifest is not None:
        if not missing:raise ValueError('A sequence named %s is already in this folder. Choose another file prefix, or enable Render missing frames to continue it.'%prefix)
        saved=json.loads(manifest.read_text(encoding='utf-8'))
        if signature is not None and saved.get('signature')!=signature:raise ValueError('Sequence scene/settings/assets differ from its completion manifest. Use a new output folder.')
        for key,value in dict(first=first,last=last,step=step,prefix=prefix,fps=fps,motion_blur=motion,digits=digits).items():
            if saved.get(key,1 if key=='step' else 'frame' if key=='prefix' else DIGITS if key=='digits' else None)!=value:raise ValueError('Sequence '+key+' differs from its saved manifest')
    recorded={v['frame']:v for v in saved.get('frames',[])}
    pending=[];completed=[]
    for frame in range(first,last+1,step):
        path=directory/frame_name(prefix,frame,digits);sidecar=path.with_name(path.stem+'.denoised.exr')
        if path.exists():
            if not missing:raise ValueError('Output exists for frame %d'%frame)
            if not valid_exr(path):raise ValueError('Existing frame is not a recognizable EXR; move it aside before recovery: '+str(path))
            if signature is not None and not saved:raise ValueError('Existing frames have no matching sequence manifest; use a new folder')
            entry=recorded.get(frame,{})
            if entry.get('sha256') and entry['sha256']!=file_hash(path):raise ValueError('Completed frame has changed: '+str(path))
            if denoise and not sidecar.exists():
                if not (path.with_name(path.name+'.postprocess')/'manifest.json').is_file():raise ValueError('Missing denoise recovery inputs for '+str(path))
                pending.append(frame);continue
            if denoise and (not valid_exr(sidecar) or entry.get('denoised_sha256') and entry['denoised_sha256']!=file_hash(sidecar)):raise ValueError('Denoised frame is invalid or has changed: '+str(sidecar))
            completed.append(dict(entry,frame=frame,file=str(path.resolve()),sha256=file_hash(path),reused=True,**({'denoised_sha256':file_hash(sidecar)} if denoise else {})))
        else:
            if sidecar.exists():raise ValueError('Orphan denoised output exists: '+str(sidecar))
            pending.append(frame)
    return pending,completed
