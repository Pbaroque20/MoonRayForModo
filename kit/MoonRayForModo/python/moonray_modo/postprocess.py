"""Persist denoising inputs when a completed beauty precedes its sidecar."""
import json,shutil
from pathlib import Path
from .assets import file_hash

def preserve(output,guides,engine):
    output=Path(output);folder=output.with_name(output.name+'.postprocess');folder.mkdir(parents=True,exist_ok=True)
    entries={}
    for key,path in guides.items():
        destination=folder/(key+'.exr');temporary=destination.with_suffix('.tmp');shutil.copyfile(path,str(temporary));temporary.replace(destination)
        entries[key]={'path':str(destination),'sha256':file_hash(destination)}
    data={'output_sha256':file_hash(output),'engine':engine,'guides':entries}
    temporary=folder/'manifest.tmp';temporary.write_text(json.dumps(data,indent=2),encoding='utf-8');temporary.replace(folder/'manifest.json')

def recover(output,engine):
    output=Path(output);manifest=output.with_name(output.name+'.postprocess')/'manifest.json'
    if not manifest.is_file():raise ValueError('Denoise inputs were not preserved for '+str(output))
    data=json.loads(manifest.read_text(encoding='utf-8'))
    if data['engine']!=engine or file_hash(output)!=data['output_sha256']:raise ValueError('Denoise recovery does not match the current beauty/denoiser')
    if set(data['guides'])!={'normal','albedo'}:raise ValueError('Incomplete denoise recovery guides')
    for entry in data['guides'].values():
        if file_hash(entry['path'])!=entry['sha256']:raise ValueError('Denoise recovery guide has changed')
    return {k:v['path'] for k,v in data['guides'].items()}
