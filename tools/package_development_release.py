"""Package a development kit/runtime with integrity checks, not render validation."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit-only',action='store_true',help='Repackage the kit while retaining the already packaged runtime archive')
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--geometry',type=Path,required=True)
    args=parser.parse_args()
    runtime=args.runtime.resolve();geometry=args.geometry.resolve()
    version=ET.parse(ROOT/'kit/MoonRayForModo/index.cfg').getroot().attrib['version']
    destination=ROOT/'dist'/('release-'+version);destination.mkdir(parents=True,exist_ok=True)
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    manifest=json.loads((runtime/'build-manifest.json').read_text(encoding='utf-8'))
    for name,entry in manifest.items():
        if digest(runtime/name)!=entry['sha256']:raise ValueError('Runtime checksum mismatch: '+name)
    build=json.loads(geometry.with_name('build.json').read_text(encoding='utf-8'))
    if not build.get('geometry_only') or digest(geometry)!=build['plugin_sha256']:raise ValueError('Geometry adapter checksum mismatch')
    def package(filename,entries,generated):
        target=destination/filename;temporary=target.with_suffix('.tmp')
        hashes={}
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as archive:
            for name,path in sorted(entries.items()):
                if name in generated:continue
                archive.write(path,name);hashes[name]={'sha256':digest(path),'bytes':path.stat().st_size}
            for name,data in sorted(generated.items()):
                archive.writestr(name,data);hashes[name]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
            archive.writestr('MoonRayForModo/'+filename.replace('.zip','-manifest.json'),json.dumps({'version':version,'revision':revision,'status':'experimental development','new_tests_run':False,'files':hashes},indent=2))
        temporary.replace(target)
        print(str(target),target.stat().st_size,flush=True)
        return target
    prefix='MoonRayForModo/'
    kit={prefix+p.relative_to(ROOT/'kit/MoonRayForModo').as_posix():p for p in (ROOT/'kit/MoonRayForModo').rglob('*') if p.is_file() and not {'__pycache__','bin'}&set(p.relative_to(ROOT/'kit/MoonRayForModo').parts) and p.suffix!='.pyc' and p.name not in ('runtime.json','development-install.json')}
    kit[prefix+'bin/MoonRayGeometry.lx']=geometry
    for source,name in [('LICENSE','LICENSE.txt'),('THIRD_PARTY.md','THIRD_PARTY.txt'),('docs/INSTALLATION.md','INSTALLATION.md'),('README.md','README.md')]:kit[prefix+name]=ROOT/source
    kit_file=package('MoonRayForModo-'+version+'-kit.zip',kit,{})
    rprefix=prefix+'runtime/'
    entries={rprefix+p.relative_to(runtime).as_posix():p for p in runtime.rglob('*') if p.is_file() and p.name!='build-manifest.json'}
    # Include dependency notices as installed by their original package providers.
    for base,label in [(ROOT/'toolchain/msys64/ucrt64/share/licenses','msys2-ucrt64'),(ROOT/'toolchain/msys64/usr/share/licenses','msys2')]:
        if base.exists():
            for p in base.rglob('*'):
                if p.is_file():entries[rprefix+'licenses/'+label+'/'+p.relative_to(base).as_posix()]=p
    sources=json.loads((ROOT/'patches/native-windows/sources.json').read_text(encoding='utf-8'))
    roots={key:ROOT/value['path'] for key,value in sources['repositories'].items()}
    roots.update(openmoonray=ROOT/'upstream/openmoonray',ispc_runtime=ROOT/'upstream/ispc-runtime')
    for key,base in roots.items():
        for p in base.iterdir():
            if p.is_file() and any(word in p.name.upper() for word in ('LICENSE','COPYING','NOTICE','THIRD-PARTY')):
                entries[rprefix+'licenses/upstream/'+key+'/'+p.name]=p
    for name in ('sources.json','xpu-sources.json','installed-packages.txt'):
        entries[rprefix+'provenance/'+name]=ROOT/'patches/native-windows'/name
    entries[rprefix+'THIRD_PARTY.md']=ROOT/'THIRD_PARTY.md'
    # Installed package descriptions retain versions, upstream URLs and license IDs.
    for folder in (ROOT/'toolchain/msys64/var/lib/pacman/local').glob('mingw-w64-ucrt-x86_64-*'):
        if (folder/'desc').is_file():entries[rprefix+'provenance/msys2/'+folder.name+'.txt']=folder/'desc'
    generated={rprefix+'build-manifest.json':json.dumps({name:{'sha256':entry['sha256'],'source':Path(entry['source']).name} for name,entry in manifest.items()},indent=2).encode(),rprefix+'provenance/SOURCES.txt':b'MSYS2 dependency source recipes: https://github.com/msys2/MINGW-packages\nPackage source/version metadata: msys2/ alongside this file.\nMoonRay port source and patches: https://github.com/Pbaroque20/MoonRayForModo\nPinned upstream source locations: sources.json\n'}
    runtime_file=destination/('MoonRayForModo-'+version+'-windows-runtime.zip')
    if args.kit_only:
        if not runtime_file.is_file():raise ValueError('Package the runtime before using --kit-only')
    else:runtime_file=package(runtime_file.name,entries,generated)
    instructions=destination/'INSTALLATION.md';instructions.write_bytes((ROOT/'docs/INSTALLATION.md').read_bytes())
    (destination/'SHA256SUMS.txt').write_text(''.join(digest(p)+'  '+p.name+'\n' for p in (kit_file,runtime_file,instructions)),encoding='utf-8')
    print('Package hashes written; no render or host tests run.',flush=True)

if __name__=='__main__':main()
