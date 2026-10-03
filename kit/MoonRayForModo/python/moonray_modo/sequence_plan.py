"""Plan sequence recovery without replacing existing render files."""
import json
from pathlib import Path

def valid_exr(path):
    path=Path(path)
    if not path.is_file() or path.stat().st_size<32:return False
    with path.open('rb') as stream:return stream.read(4)==b'\x76\x2f\x31\x01'

def plan(directory,first,last,step,prefix,fps,motion,missing=False,denoise=False,signature=None):
    from .assets import file_hash
    saved={}
    directory=Path(directory);manifest=directory/'moonray-sequence.json'
    if manifest.exists():
        if not missing:raise ValueError('Sequence exists. Enable Render missing frames to continue it.')
        saved=json.loads(manifest.read_text(encoding='utf-8'))
        if signature is not None and saved.get('signature')!=signature:raise ValueError('Sequence scene/settings/assets differ from its completion manifest. Use a new output folder.')
        for key,value in dict(first=first,last=last,step=step,prefix=prefix,fps=fps,motion_blur=motion).items():
            if saved.get(key,1 if key=='step' else 'frame' if key=='prefix' else None)!=value:raise ValueError('Sequence '+key+' differs from its saved manifest')
    recorded={v['frame']:v for v in saved.get('frames',[])}
    pending=[];completed=[]
    for frame in range(first,last+1,step):
        path=directory/('%s.%06d.exr'%(prefix,frame));sidecar=path.with_name(path.stem+'.denoised.exr')
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
