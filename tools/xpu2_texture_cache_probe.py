"""Build native mip-tile cache contracts and optional real CUDA transfer checks."""
import argparse,json,struct,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file
from xpu2_baseline import environment
from xpu2_repeatability import gpu_identity

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--gpu',action='store_true')
    a=p.parse_args();source,out=a.source.resolve(),a.output.resolve()
    if out.is_relative_to(source):p.error('Isolated output required')
    out.mkdir(parents=True,exist_ok=False);report=dict(status='incomplete',scope='Native read-only tile cache; CUDA byte-transfer checks, not texture filtering or image rendering',runs=[])
    try:
        compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe';include=source/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include'
        env=environment(compiler.parent,out)
        files=[ROOT/'xpu2'/s for s in ('texture_cache.h','texture_cache_test.cc','texture_residency.h','texture_residency_test.cc')]+[Path(__file__).resolve()]
        cases=[('contract',ROOT/'xpu2/texture_cache_test.cc'),('residency',ROOT/'xpu2/texture_residency_test.cc')]
        if a.gpu:
            files += [ROOT/'xpu2/texture_cuda_backend.h',ROOT/'xpu2/texture_cache_gpu_probe.cc'];cases.append(('cuda',files[-1]));report['gpu']=gpu_identity()
        hashes={str(f):digest_file(f) for f in files}
        # Exact RGBA float32 payloads with distinct revision/mip values. No claim
        # that this generator matches native OIIO mip filtering.
        fixtures={}
        for revision,mip,side in ((1,0,64),(1,1,32),(2,0,64)):
            data=b''.join(struct.pack('<4f',revision/4,x/side,y/side,1) for y in range(side) for x in range(side))
            path=out/f'r{revision}m{mip}.tile';path.write_bytes(data);fixtures[path.name]=digest_file(path)
        flags=['-std=c++17','-O2','-mavx','-mno-avx2','-mno-fma','-ffp-contract=off','-I'+str(include)]
        for name,cpp in cases:
            print('build '+name,flush=True);exe=out/(name+'.exe');pp=out/(name+'.ii')
            for label,command in [('preprocess',['-E',str(cpp),'-o',str(pp)]),('compile',[str(pp),'-o',str(exe)])]:
                done=subprocess.run([str(compiler),*flags,*command],env=env,capture_output=True,text=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
                (out/(name+'-'+label+'.log')).write_text(done.stdout+done.stderr)
                if done.returncode:raise ValueError(name+' '+label+' failed')
            print('run '+name,flush=True)
            done=subprocess.run([str(exe),*([str(out)] if name=='cuda' else [])],env=env,capture_output=True,text=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
            (out/(name+'-run.log')).write_text(done.stdout+done.stderr)
            if done.returncode:raise ValueError(name+' failed: '+done.stderr)
            checks=json.loads(done.stdout)
            if checks.get('passed') is not True:raise ValueError('Incomplete '+name)
            report['runs'].append(dict(case=name,checks=checks,executable_sha256=digest_file(exe),preprocessed_sha256=digest_file(pp)))
        if hashes!={str(f):digest_file(f) for f in files}:raise ValueError('Source drift')
        if a.gpu and gpu_identity()!=report['gpu']:raise ValueError('GPU drift')
        report.update(status='passed',source_hashes=hashes,fixture_hashes=fixtures,compiler_sha256=digest_file(compiler))
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
