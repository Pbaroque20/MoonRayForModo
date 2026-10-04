"""Check three-category checkpoint restoration against an uninterrupted render.
Uses a controlled four-sample checkpoint stop, then resumes to sixteen samples.
This does not simulate power loss or an interrupted checkpoint write.
Run with the toolchain Python (OpenImageIO required); nothing runs without --run.
"""
import argparse,json,re,subprocess
from pathlib import Path
from validate_crypto_categories import fixture,native,rdla
from check_crypto_coverage import read,difference

def verify_log(log,mode,resume=False):
    errors=re.findall(r'^Error:.*$',log,re.MULTILINE)
    if errors:raise RuntimeError('; '.join(errors[:3]))
    if mode=='xpu' and native.execution_status(log)!='XPU active (NVIDIA GPU + CPU)':raise RuntimeError('XPU fallback')
    if resume:
        samples=re.search(r'progressCheckpointTileSamples:(\d+)',log)
        if 'resume render initial information {' not in log or not samples or int(samples.group(1))<=0:
            raise RuntimeError('No confirmation that saved samples were restored')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--run',action='store_true');args=parser.parse_args()
    if not args.run:print('Use --run to execute controlled checkpoint checks.');return
    folder=args.output.resolve();folder.mkdir(parents=True,exist_ok=False)
    runtime=args.runtime.resolve();env=native.environment(runtime);report={'runtime_capability':json.loads((runtime/'modo-crypto-categories.json').read_text(encoding='utf-8')),'checks':[]}
    if not native.supports_crypto_categories(runtime):raise ValueError('Category-capable candidate required')
    def render(mode,name,resume=False,cap=0,checkpoint=None):
        scene=fixture('presence');image=folder/(mode+'-'+name+'.exr');source=image.with_suffix('.rdla')
        scene['_recovery']={'file':str(checkpoint),'resume':resume,'minutes':.1,'guides':{}}
        text=rdla.scene_text(scene,128,128,4,.3,str(image))
        text=text.replace('["checkpoint_active"] = true,','["checkpoint_active"] = true,\n  ["checkpoint_mode"] = 1,\n  ["checkpoint_quality_steps"] = 4,\n  ["checkpoint_sample_cap"] = '+str(cap)+',')
        source.write_text(text,encoding='utf-8')
        with source.with_suffix('.log').open('w',encoding='utf-8') as log:
            process=subprocess.Popen([str(runtime/'moonray.exe'),*native.arguments(source,image,4,mode)],env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:code=process.wait(timeout=180)
            except BaseException:process.kill();process.wait();raise
        if code:raise RuntimeError(name+' exit '+str(code))
        log=source.with_suffix('.log').read_text(encoding='utf-8',errors='replace')
        verify_log(log,mode,resume)
        return image
    for mode in ('scalar','vector','xpu'):
        try:
            checkpoint=folder/(mode+'-checkpoint.exr')
            render(mode,'partial',cap=4,checkpoint=checkpoint)
            if not checkpoint.is_file():raise RuntimeError('No checkpoint')
            # Preserve the partial checkpoint for inspection before resume overwrites it.
            partial=folder/(mode+'-partial-checkpoint.exr');partial.write_bytes(checkpoint.read_bytes())
            resumed=render(mode,'resumed',resume=True,checkpoint=checkpoint)
            reference=render(mode,'reference',checkpoint=folder/(mode+'-reference-checkpoint.exr'))
            for part,category in enumerate(('object','material','asset'),1):
                initial,_,_=read(partial,part)
                a,manifest,found=read(resumed,part);b,expected,_=read(reference,part)
                error=difference(a,b);progress=difference(initial,b)
                report['checks'].append({'mode':mode,'category':category,'max_coverage_difference':error,'partial_to_final_difference':progress,'visible_ids':len(found),'passed':error<=1e-6 and progress>1e-6 and manifest==expected and len(found)=={'object':3,'material':2,'asset':1}[category]})
        except Exception as exc:report['checks'].append({'mode':mode,'passed':False,'error':str(exc)})
        (folder/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    report['passed']=all(v['passed'] for v in report['checks'])
    (folder/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
    if not report['passed']:raise SystemExit(1)
if __name__=='__main__':main()