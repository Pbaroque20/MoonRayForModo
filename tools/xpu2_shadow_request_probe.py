"""Build a borrowed-scene shadow adapter against frozen objects and validate renders.

Diagnostic only; never installs a runtime or modifies the source checkout.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file,inventory,verify
from xpu2.images import read_rgba,compare_rgba
from xpu2.shadow_requests import summarize
from xpu2_baseline import environment
from xpu2_repeatability import successful,gpu_identity

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,type=Path)
    p.add_argument('--frozen-build',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();source,base,out=a.source.resolve(),a.frozen_build.resolve(),a.output.resolve()
    if out.is_relative_to(source) or out.is_relative_to(base):p.error('Output must be isolated')
    out.mkdir(parents=True,exist_ok=False);report=dict(status='incomplete',cases=[])
    try:
        manifest=json.loads((base/'build-inputs.json').read_text())
        if manifest.get('status')!='built':raise ValueError('Frozen build incomplete')
        original=source/'upstream/openmoonray/moonray/moonray/lib/rendering/pbr/handlers/XPURayHandlers.cc'
        if digest_file(original)!=manifest['source_sha256']:raise ValueError('Native handler drift')
        for item in manifest['inputs']:
            if digest_file(base/item['copy'])!=item['sha256']:raise ValueError('Frozen object changed')
        runtime=out/'runtime';shutil.copytree(base/'control',runtime)
        if digest_file(runtime/'librendering_rndr.dll')!=manifest['control_dll_sha256']:raise ValueError('Control runtime drift')
        compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe'
        env=environment(runtime,out);env['PATH']=str(compiler.parent)+os.pathsep+env['PATH']
        def run(args,label,timeout=300):
            print(label,flush=True)
            with (out/(label+'.log')).open('w',encoding='utf-8') as log:
                done=subprocess.run(args,cwd=out,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW)
            if done.returncode:raise ValueError(label+' failed; see '+str(out/(label+'.log')))
        test=out/'contract.exe'
        run([str(compiler),'-std=c++17','-O2','-Wall','-Wextra',str(ROOT/'xpu2/shadow_request_test.cc'),'-o',str(test)],'build-contract')
        run([str(test)],'contract');report['native_contract']='passed'
        anchor='    unsigned char *isOccluded = accel->getOutputOcclusionBuf(tls->mThreadIdx);'
        text=original.read_text()
        if text.count(anchor)!=1:raise ValueError('Native shadow anchor drift')
        text=text.replace(anchor,anchor+'\n'+(ROOT/'xpu2/shadow_request_probe.inc').read_text())
        text='#include <algorithm>\n#include <vector>\n#include <cstring>\n#include "shadow_request.h"\n'+text
        text=(ROOT/'xpu2/trace_output.h').read_text()+'\n'+text.replace('std::fprintf(stderr,','std::fprintf(xpu2TraceOutput(),')
        cc=out/'XPURayHandlers.cc';cc.write_text(text)
        args=manifest['compile_command'].copy();args[0]=str(compiler)
        args[args.index('-o')+1]=str(out/'shadow.obj');args[args.index('-c')+1]=str(cc)
        args+=['-I'+str(ROOT/'xpu2')]
        # Freeze the resolved source/header view; verify it again after compile.
        pp=args[:args.index('-o')]+['-I'+str(ROOT/'xpu2'),'-E',str(cc),'-o',str(out/'before.ii')]
        run(pp,'preprocess-before');run(args,'compile')
        pp[-1]=str(out/'after.ii');run(pp,'preprocess-after')
        if digest_file(out/'before.ii')!=digest_file(out/'after.ii'):raise ValueError('Header drift during build')
        lines=(base/'control.rsp').read_text().splitlines()
        anchors=[line for line in lines if line.strip().strip('"').endswith('-XPURayHandlers.cc.obj')]
        if len(anchors)!=1:raise ValueError('Frozen handler link anchor drift')
        rsp=out/'link.rsp';rsp.write_text('\n'.join('"'+str(out/'shadow.obj').replace('\\','/')+'"' if line in anchors else line for line in lines))
        run([str(compiler),'-O3','-DNDEBUG','-shared','-o',str(runtime/'librendering_rndr.dll'),'@'+str(rsp)],'link')
        held=inventory(runtime);gpu=gpu_identity()
        if not gpu:raise ValueError('No GPU identity')
        report['implementation_sha256']={str(p.relative_to(ROOT)):digest_file(p) for p in (ROOT/'xpu2/shadow_request.h',ROOT/'xpu2/shadow_request_probe.inc',ROOT/'xpu2/shadow_requests.py',ROOT/'xpu2/shadow_request_test.cc',Path(__file__))}
        report.update(gpu_driver_identity=gpu,scope='Synchronous borrowed native scene, standard surface shadow requests, frozen native link objects',build=dict(source_sha256=digest_file(original),preprocessed_sha256=digest_file(out/'before.ii'),dll_sha256=digest_file(runtime/'librendering_rndr.dll'),frozen_manifest_sha256=digest_file(base/'build-inputs.json')))
        for name,path in [('unit',ROOT/'test-results/xpu2-origins/unit/scene.rdla'),('blocker',ROOT/'test-results/xpu2-origins-blockers/gap_0.0001/scene.rdla')]:
            case=out/name;case.mkdir();scene=case/'scene.rdla';shutil.copy2(path,scene)
            entry=dict(name=name,scene_sha256=digest_file(scene),runs=[]);report['cases'].append(entry);images={}
            for label in ('reference','control','probe'):
                folder=case/label;folder.mkdir();rt=base/'control' if label=='reference' else runtime
                renderenv=environment(rt,folder)
                if label=='probe':renderenv.update(XPU2_PROBE_SHADOW_REQUESTS='1',XPU2_TRACE_FILE=str(folder/'trace.jsonl'))
                command=[str(rt/'moonray.exe'),'-in',str(scene),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads','1','-info','-stats',str(folder/'stats.csv')]
                print(name+' '+label,flush=True)
                with (folder/'render.log').open('w') as log:
                    done=subprocess.run(command,cwd=folder,env=renderenv,stdout=log,stderr=subprocess.STDOUT,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
                logs=(folder/'render.log').read_text(errors='replace');stats=(folder/'stats.csv').read_text(errors='replace')
                result=successful('xpu',1,done.returncode,logs,stats,(folder/'beauty.exr').exists())
                entry['runs'].append(dict(result,label=label))
                if not result['passed']:raise ValueError('Render failed: '+name+' '+label)
                images[label]=read_rgba(rt,folder/'beauty.exr',folder,'raw',renderenv)
                if label=='probe':
                    trace=(folder/'trace.jsonl').read_text();entry['shadow_requests']=summarize(trace)
                    entry['trace_sha256']=digest_file(folder/'trace.jsonl')
            entry['trace_off_image']=compare_rgba(images['reference'],images['control'])
            entry['trace_on_image']=compare_rgba(images['control'],images['probe'])
            if any(entry[k]['status']!='passed' for k in ('trace_off_image','trace_on_image')):raise ValueError('Diagnostic changed final image')
        if not all(any(c['shadow_requests'][kind] for c in report['cases']) for kind in ('blocked','visible')):raise ValueError('Missing blocked/visible coverage')
        verify(runtime,held)
        for item in manifest['inputs']:
            if digest_file(base/item['copy'])!=item['sha256']:raise ValueError('Frozen input drift')
        if gpu_identity()!=gpu:raise ValueError('GPU changed')
        report['backend_parity']='failed' if any(c['shadow_requests']['backend_parity']!='passed' for c in report['cases']) else 'passed'
        report['status']='passed' # Request adapter only; backend parity is separately gated.
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2))
    print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
