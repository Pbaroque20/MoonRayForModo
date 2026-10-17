"""Build an isolated original-ISPC light oracle and generate live-light references."""
import json
import os
from pathlib import Path
import shlex
import struct
import subprocess
from xpu2.reference import digest_file
from xpu2.live_env import coverage
from xpu2_baseline import environment
ROOT=Path(__file__).resolve().parents[1]

def prepare(rows,source,out):
    original=source/'upstream/openmoonray/moonray/moonray/lib/rendering/pbr/light/EnvLight.ispc'
    native=ROOT/'test-results/xpu2-native-vector-original-regression'
    resume=ROOT/'test-results/xpu2-owned-contribution-validation/resume.obj'
    runtime=ROOT/'test-results/xpu2-origin-build/trace'
    compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe';ispc=compiler.with_name('ispc.exe')
    folder=out/'native';folder.mkdir()
    env=environment(runtime,folder);env['PATH']=str(compiler.parent)+os.pathsep+env['PATH']
    sourcefile=folder/'env.ispc';sourcefile.write_text(original.read_text()+'\n'+(ROOT/'xpu2/live_env_oracle.ispc.inc').read_text(encoding='utf-8-sig'))
    ninja=(source/'build/native-renderer-avx/build.ninja').read_text()
    stanza=next(s for s in ninja.split('\n\n') if s.startswith('build ') and 'EnvLight.ispc.obj' in s.splitlines()[0] and 'ISPC_COMPILER' in s.splitlines()[0])
    variables=dict(line.strip().split(' = ',1) for line in stanza.splitlines()[1:] if ' = ' in line)
    flags=shlex.split(' '.join(variables[k] for k in ('DEFINES','INCLUDES','FLAGS')))
    if '--opt=force-aligned-memory' in flags:flags.remove('--opt=force-aligned-memory')
    flags+=['-I'+str(original.parent)]
    def run(args,label):
        print(label,flush=True);d=subprocess.run(args,env=env,capture_output=True,text=True,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
        (folder/(label+'.log')).write_text(d.stdout+d.stderr)
        if d.returncode:raise ValueError(label+' failed: '+d.stderr[-2000:])
        return d.stdout
    pp=folder/'env.preprocessed.ispc';pp.write_text(run([str(ispc),*flags,'-E',str(sourcefile)],'preprocess'))
    obj=folder/'env.obj';run([str(ispc),*flags,str(sourcefile),'--emit-obj','-o',str(obj)],'compile')
    if pp.read_text()!=run([str(ispc),*flags,'-E',str(sourcefile)],'verify'):raise ValueError('Native header drift')
    lines=(native/'link.rsp').read_text().splitlines();removed=[s for s in lines if s.strip().strip('"').endswith('-EnvLight.ispc.obj')]
    if len(removed)!=1:raise ValueError('Native EnvLight link anchor drift')
    rsp=folder/'link.rsp';rsp.write_text('\n'.join(s for s in lines if s not in removed))
    exe=folder/'env.exe';run([str(compiler),'-std=c++17','-O2','-mavx','-mno-avx2','-mno-fma','-ffp-contract=off',str(ROOT/'xpu2/live_env_oracle.cc'),str(obj),str(native/'lambert_sample.obj'),str(resume),'@'+str(rsp),'-o',str(exe)],'link')
    maximum=struct.unpack('<f',struct.pack('<I',0x7f7fffff))[0]
    variants=[('sphere',[.3,.3,.3,1,1,1,0,0,0,1,maximum]),
              ('tinted',[2,.5,.125,.5,.8,.2,0,0,0,1,maximum]),
              ('black',[0,0,0,1,1,1,0,0,0,1,maximum]),
              ('hemisphere_up',[.3,.3,.3,1,1,1,1,0,0,1,maximum]),
              ('hemisphere_down',[.3,.3,.3,1,1,1,1,0,0,-1,maximum]),
              ('short_ray',[.3,.3,.3,1,1,1,0,0,0,1,1])]
    cases=[];raw=bytearray()
    for name,params in variants:
        params=params+[0.]*(16-len(params));words=list(struct.unpack('<16I',struct.pack('<16f',*params)))
        for original_row in rows:
            row=dict(original_row);row['variant']=name;row['contribution']=list(row['contribution'])
            # Poison captured light values: the new path must recompute them.
            for k in (4,5,6,14,15,16):row['contribution'][k]=0
            row['contribution']+=words;cases.append(row)
            raw+=struct.pack('<64I',*(row['lambert']+row['contribution']))
    inp=folder/'input.bin';inp.write_bytes(raw);output=folder/'output.bin';run([str(exe),str(inp),str(output)],'oracle')
    result=output.read_bytes()
    if len(result)!=len(cases)*96:raise ValueError('Native oracle output length')
    for i,row in enumerate(cases):
        words=list(struct.unpack_from('<24I',result,i*96));row['sample']=words[:8];row['expected']=words[8:]
    deps=[ROOT/'xpu2/live_env.py',original,ROOT/'xpu2/live_env_oracle.ispc.inc',ROOT/'xpu2/live_env_oracle.cc',Path(__file__),compiler,ispc,native/'lambert_sample.obj',resume,exe,pp,obj,inp,output,rsp]
    deps += [Path(s.strip().strip('"')) for s in lines if Path(s.strip().strip('"')).is_file()]
    info=dict(coverage=coverage(cases),flags=flags,hashes={str(f):digest_file(f) for f in deps},variants=[n for n,_ in variants],cases=len(cases),native_functions=['LambertBsdfLobe_sample','EnvLight_intersect','EnvLight_eval','integrateBsdfSample'])
    return cases,info
