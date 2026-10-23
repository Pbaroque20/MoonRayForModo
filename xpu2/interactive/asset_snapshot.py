"""Private asset freezing on the scene-service worker; no mip regeneration.

Discovered files are copied (never hardlinked), hashed and rewritten on an owned
RDLB copy. A manifest is published last. This cannot discover arbitrary files
opened internally by a DSO: inspect coverage before calling a scene self-contained.
"""
import hashlib
import json
import re
import subprocess
from pathlib import Path
from fallback import environment
from reference_runtime import sha,identity


def native(helper,runtime,folder,mode,scene,*args):
    r=subprocess.run([str(helper),mode,str(scene),environment(runtime,folder)['RDL2_DSO_PATH'],*map(str,args)],
        env=environment(runtime,folder),cwd=folder,capture_output=True,text=True,encoding='utf-8',
        timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if r.returncode:raise ValueError('Native asset '+mode+' failed: '+r.stderr[-1000:])
    return json.loads(r.stdout)


def members(value,base,max_members=100000):
    if any(x in value for x in ('$','%','*','?','\x00')):raise ValueError('Unsupported asset expression: '+value)
    path=Path(value)
    if not path.is_absolute():path=base/path
    tokens=re.findall(r'<UDIM>|UDIM',path.name)
    if tokens:
        if len(tokens)!=1:raise ValueError('Ambiguous UDIM expression')
        token=tokens[0]
        regex=re.compile(re.escape(path.name).replace(re.escape(token),r'([1-9][0-9]{3})'))
        files=[]
        for member in path.parent.iterdir():
            match=regex.fullmatch(member.name)
            if match and int(match[1])>=1001:
                if len(files)>=max_members:raise ValueError('Asset member budget exceeded')
                files.append(member)
        files.sort()
    else:
        if '<' in str(path) or '>' in str(path):raise ValueError('Unsupported asset token')
        files=[path]
    if not files:raise FileNotFoundError('Missing asset: '+value)
    for f in files:
        # Do not silently follow a link into a mutable or unexpected asset tree.
        if any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()) for p in (f,*f.parents)):
            raise ValueError('Linked assets require explicit resolution: '+str(f))
        if not f.is_file():raise FileNotFoundError('Missing asset: '+str(f))
    return path,files,bool(tokens)


def freeze(scene,helper,runtime,out,base,*,max_bytes=8<<30,max_files=100000):
    scene,helper,runtime,out,base=map(lambda p:Path(p).absolute(),(scene,helper,runtime,out,base))
    if not scene.is_file() or scene.suffix.lower()!='.rdlb':raise ValueError('Frozen RDLB required')
    if max_bytes<=0 or max_files<=0:raise ValueError('Positive asset budgets required')
    out.mkdir(parents=True,exist_ok=False)
    before=sha(scene)
    scan=native(helper,runtime,out,'inspect',scene)
    mappings=[];files={};copied={};total=0
    for reference in scan['references']:
        pattern,inputs,tiled=members(reference['value'],base,max_files)
        # Per-source-pattern directory preserves UDIM basenames and addressing.
        folder=out/'assets'/hashlib.sha256(str(pattern).encode()).hexdigest()
        folder.mkdir(parents=True,exist_ok=True)
        for asset in inputs:
            dest=folder/asset.name
            key=str(dest.relative_to(out).as_posix())
            if key in files:continue
            stat=asset.stat();size=stat.st_size
            if len(files)>=max_files or size>max_bytes-total:raise ValueError('Asset snapshot budget exceeded')
            total+=size
            digest=hashlib.sha256();written=0
            with asset.open('rb') as src,dest.open('xb') as dst:
                while data:=src.read(1<<20):
                    written+=len(data)
                    if written>size:raise ValueError('Asset changed during capture: '+str(asset))
                    dst.write(data);digest.update(data)
            after=asset.stat()
            value=digest.hexdigest()
            if written!=size or (stat.st_size,stat.st_mtime_ns,stat.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino) or sha(asset)!=value:
                raise ValueError('Asset changed during capture: '+str(asset))
            # Multiple references to the same source must freeze the same version.
            prior=copied.setdefault(str(asset),value)
            if prior!=value:raise ValueError('Inconsistent source version: '+str(asset))
            files[key]={'sha256':value,'bytes':size,'source':str(asset)}
        mappings.append({**reference,'replacement':str(folder/pattern.name)})
    (out/'mapping.json').write_text(json.dumps(mappings,indent=2)+'\n',encoding='utf-8')
    rewritten=native(helper,runtime,out,'rewrite',scene,out/'mapping.json',out/'scene.rdlb')
    if sha(scene)!=before:raise ValueError('Canonical scene changed during capture')
    if len(rewritten['references'])!=len(mappings) or any(a['value']!=b['replacement'] for a,b in zip(rewritten['references'],mappings)):
        raise ValueError('Native asset rewrite failed')
    contract={'schema':1,'scene_sha256':sha(out/'scene.rdlb'),'source_scene_sha256':before,'bytes':total,
              'files':files,'coverage':scan['coverage'],'unclassified_strings':scan['unclassified_strings'],
              'references':mappings,'helper_sha256':sha(helper)}
    for source_path,digest in copied.items():
        if sha(Path(source_path))!=digest:raise ValueError('Asset changed before publication: '+source_path)
    manifest={'identity':identity(contract),'contract':contract}
    # Marker is written only after every native and asset operation succeeds.
    temp=out/'manifest.pending';temp.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    verify(temp)
    temp.rename(out/'manifest.json')
    return out/'manifest.json'


def verify(manifest):
    manifest=Path(manifest);root=manifest.parent
    data=json.loads(manifest.read_text(encoding='utf-8'));c=data['contract']
    if data['identity']!=identity(c):raise ValueError('Asset manifest changed')
    for ref in c['references']:
        if not Path(ref['replacement']).resolve().is_relative_to(root.resolve()):
            raise ValueError('Asset package was moved; paths must be rewritten')
    if sha(root/'scene.rdlb')!=c['scene_sha256']:raise ValueError('Frozen scene changed')
    expected=set(c['files']);actual=set()
    for p in (root/'assets').rglob('*'):
        if p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()):raise ValueError('Linked frozen asset')
        if p.is_file():actual.add(p.relative_to(root).as_posix())
    if actual!=expected:raise ValueError('Frozen assets added or removed')
    for name,entry in c['files'].items():
        path=root/name
        if not path.resolve().is_relative_to(root.resolve()):raise ValueError('Asset escaped package')
        if path.stat().st_size!=entry['bytes'] or sha(path)!=entry['sha256']:raise ValueError('Frozen asset changed: '+name)
    return root/'scene.rdlb'
