"""Prepare an isolated three-category render review; renders only with --run.
This checks process completion and EXR structure. Pixel coverage, compositing and
checkpoint equivalence still require inspection of the generated renders.
"""
import argparse,copy,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'kit/MoonRayForModo/python'))
from moonray_modo import native,rdla

def fixture():
    meshes=[]
    for index in range(3):
        shift=(index-1)*.65
        meshes.append({'identity':'object'+str(index),'name':'Triangle '+str(index),'material':str(index%2),
            'vertices':[[-.55+shift,-.5,-index*.05],[.55+shift,-.5,-index*.05],[shift,.6,-index*.05]],
            'faces':[[0,1,2]],'matrix':rdla.IDENTITY})
    return {'camera':{'matrix':[1,0,0,0,0,1,0,0,0,0,1,0,0,0,4,1],'film_mm':36,'focal_mm':50},
      'meshes':meshes,'materials':{'0':{'name':'Shared red','color':[.8,.1,.1]},'1':{'name':'Blue','color':[.1,.1,.8]}},
      'lights':[],'_crypto_categories':True,
      'production':{'objects':{m['identity']:{'asset_label':'assembly'} for m in meshes}},
      'custom_aovs':[{'name':'Mask_'+c,'kind':'cryptomatte','category':c} for c in ('object','material','asset')]}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--run',action='store_true');parser.add_argument('--timeout',type=int,default=180)
    args=parser.parse_args();folder=args.output.resolve()
    if folder.exists() and any(folder.iterdir()):parser.error('Choose an empty output directory')
    folder.mkdir(parents=True,exist_ok=True)
    runtime=args.runtime.resolve();report={'status':'prepared_not_run','cases':[],
      'manual_checks':['Three object IDs, two material IDs, one asset ID.',
       'Material/asset coverage combines overlapping object contributions before ranking.',
       'Each EXR category part has its own correct manifest.',
       'Check presence, motion blur, instancing and checkpoint resume separately.',
       'Volume coverage is unsupported and must not be signed off by this check.']}
    for mode in ('scalar','vector','xpu'):
        for cat in ('all','object','material','asset'):
            name=mode+'-'+cat;scene=fixture()
            if cat!='all':scene['custom_aovs']=[v for v in scene['custom_aovs'] if v['category']==cat]
            source=folder/(name+'.rdla');image=folder/(name+'.exr')
            source.write_text(rdla.scene_text(scene,128,128,2,.3,str(image)),encoding='utf-8')
            command=[str(runtime/'moonray.exe'),*native.arguments(source,image,4,mode)]
            report['cases'].append({'name':name,'command':command,'image':str(image),'status':'not_run'})
    path=folder/'report.json'
    def save():path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    save()
    if not args.run:print('Prepared only:',path);return
    if not native.supports_crypto_categories(runtime):raise ValueError('Matching category-enabled runtime required')
    env=native.environment(runtime);flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    for case in report['cases']:
        try:
            with (folder/(case['name']+'.log')).open('w',encoding='utf-8') as log:
                process=subprocess.Popen(case['command'],stdout=log,stderr=subprocess.STDOUT,env=env,creationflags=flags)
                try:code=process.wait(timeout=args.timeout)
                except BaseException:process.kill();process.wait(timeout=15);raise
            if code:raise RuntimeError('Renderer exit '+str(code))
            result=subprocess.run([str(runtime/'oiiotool.exe'),'--info','-v','-a',case['image']],env=env,capture_output=True,text=True,timeout=60,creationflags=flags)
            (folder/(case['name']+'-info.txt')).write_text(result.stdout+result.stderr,encoding='utf-8')
            if result.returncode or 'Cryptomatte00' not in result.stdout:raise RuntimeError('Missing/unreadable Cryptomatte output')
            if case['name'].endswith('-all') and any('crypto_'+c not in result.stdout for c in ('object','material','asset')):raise RuntimeError('Missing category part')
            if case['name'].startswith('xpu') and native.execution_status((folder/(case['name']+'.log')).read_text(encoding='utf-8',errors='replace'))!='XPU active (NVIDIA GPU + CPU)':raise RuntimeError('XPU not confirmed; fallback is not a pass')
            case['status']='rendered_requires_coverage_review'
        except Exception as exc:case.update(status='failed',error=str(exc))
        save()
    report['status']='failed' if any(c['status']=='failed' for c in report['cases']) else 'rendered_requires_coverage_review';save();print(path)

if __name__=='__main__':main()
