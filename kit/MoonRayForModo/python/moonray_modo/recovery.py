"""Stable native checkpoints outside temporary renderer workspaces."""
import hashlib,json,math
from pathlib import Path
from .sequence_plan import valid_exr

def values(settings):
    result={'enabled':settings.get('enabled',False),'resume':settings.get('resume',True),'minutes':settings.get('minutes',1.0)}
    if type(result['enabled']) is not bool or type(result['resume']) is not bool:raise ValueError('Invalid checkpoint setting')
    if type(result['minutes']) not in (int,float) or not math.isfinite(result['minutes']) or not .1<=result['minutes']<=1440:raise ValueError('Checkpoint interval must be 0.1–1440 minutes')
    return result

def prepare(snapshot,destination,width,height,samples,environment,runtime):
    settings=values(snapshot.get('recovery',{}))
    if not settings['enabled']:return None
    destination=Path(destination).resolve();folder=destination.with_name(destination.name+'.recovery');folder.mkdir(parents=True,exist_ok=True)
    clean={k:v for k,v in snapshot.items() if k not in ('recovery','display','preview_buffer','_denoise_guides','warnings','_geometry_revision')}
    assets={}
    def scan(value):
        if isinstance(value,dict):
            for child in value.values():scan(child)
        elif isinstance(value,list):
            for child in value:scan(child)
        elif isinstance(value,str) and len(value)<4096:
            try:
                path=Path(value)
                if path.is_absolute() and path.is_file():assets[str(path)]=[path.stat().st_size,path.stat().st_mtime_ns]
                elif '<UDIM>' in value:
                    from .textures import source_tiles
                    for path in source_tiles(value).values():assets[str(path)]=[path.stat().st_size,path.stat().st_mtime_ns]
            except (OSError,ValueError):pass
    scan(clean)
    executable=Path(runtime)/'moonray.exe'
    signature=hashlib.sha256(json.dumps([clean,assets,width,height,samples,environment,str(executable),executable.stat().st_mtime_ns],sort_keys=True).encode('utf-8')).hexdigest()
    manifest=folder/'manifest.json';checkpoint=folder/'frame.exr'
    guides={key:folder/('guide-'+key+'.exr') for key in snapshot.get('_denoise_guides',{})}
    expected=[checkpoint,*guides.values()]
    if manifest.exists():
        saved=json.loads(manifest.read_text(encoding='utf-8'))
        if saved.get('signature')!=signature:raise ValueError('Recovery data belongs to different scene/settings/assets. Choose another output filename or move its .recovery folder aside.')
    elif any(folder.iterdir()):raise ValueError('Recovery folder has no manifest; choose another output filename')
    existing=[path for path in expected if path.exists()]
    if existing and not settings['resume']:raise ValueError('A checkpoint already exists. Enable Resume matching checkpoint or choose another output filename.')
    if existing and (len(existing)!=len(expected) or not all(valid_exr(path) for path in expected)):raise ValueError('Incomplete checkpoint files; preserve or move the .recovery folder before retrying')
    staged=manifest.with_suffix('.tmp');staged.write_text(json.dumps({'signature':signature,'output':str(destination),'files':[str(p) for p in expected]},indent=2),encoding='utf-8');staged.replace(manifest)
    return {'file':str(checkpoint),'guides':{k:str(v) for k,v in guides.items()},'resume':bool(existing),'minutes':settings['minutes']}

def attributes(recovery,key=None):
    if not recovery:return {}
    path=recovery['guides'][key] if key is not None else recovery['file']
    return {'checkpoint_file_name':path,'resume_file_name':path if recovery['resume'] else ''}
