"""Freeze a local RDL scene for the private standalone XPU2 prototype."""
import argparse,json,shutil,subprocess
from pathlib import Path
import asset_snapshot
from reference_runtime import sha,verify
from fallback import environment
HERE=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('scene','build','runtime','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();scene=a.scene.resolve();rt=a.runtime.resolve();out=a.output.resolve()
    if scene.suffix.lower() not in ('.rdla','.rdlb') or not scene.is_file():p.error('Existing RDLA or RDLB scene required')
    if out.is_relative_to(rt):p.error('Output must be outside the pinned runtime')
    build=json.loads(a.build.read_text());assert build['status']=='passed';helper=Path(build['helper'])
    if sha(helper)!=build['asset_build']['executable_sha256']:raise ValueError('Asset helper changed')
    verify(rt,json.loads((HERE/'reference-lock.json').read_text()));out.mkdir(parents=True,exist_ok=False)
    before=sha(scene)
    if scene.suffix.lower()=='.rdlb':shutil.copyfile(scene,out/'input.rdlb')
    else:
        result=subprocess.run([str(rt/'rdl2_convert.exe'),'-i',str(scene),'-o',str(out/'input.rdlb')],cwd=scene.parent,env=environment(rt,out),capture_output=True,text=True,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (out/'convert.log').write_text(result.stdout+result.stderr,encoding='utf-8')
        if result.returncode:raise RuntimeError('Scene conversion failed; see convert.log')
    manifest=asset_snapshot.freeze(out/'input.rdlb',helper,rt,out/'frozen',scene.parent)
    if sha(scene)!=before:raise RuntimeError('Source scene changed during capture')
    print(manifest,flush=True)
if __name__=='__main__':main()
