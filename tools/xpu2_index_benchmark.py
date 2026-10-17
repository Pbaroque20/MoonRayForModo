"""Compare identical metadata updates against the recorded pre-optimization index."""
import argparse,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file
from xpu2_baseline import environment


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();source,out=a.source.resolve(),a.output.resolve()
    if out.is_relative_to(source):p.error('Isolated output required')
    out.mkdir(parents=True,exist_ok=False);report=dict(status='incomplete',scope='Synthetic 10,001-entity metadata benchmark; not scene loading or rendering',runs=[])
    try:
        compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe';env=environment(compiler.parent,out)
        old=subprocess.run(['git','show','b01f841:xpu2/indexed_scene.h'],cwd=ROOT,capture_output=True,check=True).stdout
        sources=[ROOT/'xpu2'/n for n in ('indexed_scene.h','persistent_map.h','indexed_scene_benchmark.cc')]
        hashes={str(f.relative_to(ROOT)):digest_file(f) for f in sources}
        for label in ('baseline','shared'):
            folder=out/label;folder.mkdir();code=folder/'benchmark.cc';code.write_bytes(sources[2].read_bytes())
            (folder/'indexed_scene.h').write_bytes(old if label=='baseline' else sources[0].read_bytes())
            if label=='shared':(folder/'persistent_map.h').write_bytes(sources[1].read_bytes())
            command=[str(compiler),'-std=c++17','-O2','-mavx','-mno-avx2','-mno-fma','-ffp-contract=off',str(code),'-o',str(folder/'benchmark.exe')]
            done=subprocess.run(command,env=env,capture_output=True,text=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
            (folder/'compile.log').write_text(done.stdout+done.stderr,encoding='utf-8')
            if done.returncode:raise ValueError(label+' build failed')
        for pair in range(3):
            for label in (('baseline','shared') if pair%2==0 else ('shared','baseline')):
                done=subprocess.run([str(out/label/'benchmark.exe')],env=env,capture_output=True,text=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
                if done.returncode:raise ValueError(label+' run failed: '+done.stderr)
                result=json.loads(done.stdout)
                if result.get('passed') is not True or result.get('updates')!=100:raise ValueError('Incomplete benchmark')
                report['runs'].append(dict(pair=pair,label=label,**result))
        if hashes!={str(f.relative_to(ROOT)):digest_file(f) for f in sources}:raise ValueError('Source drift')
        report.update(status='passed',source_hashes=hashes,baseline_commit='b01f841',compiler_sha256=digest_file(compiler),executables={name:digest_file(out/name/'benchmark.exe') for name in ('baseline','shared')})
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
