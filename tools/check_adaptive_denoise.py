"""Small adaptive XPU render and both denoisers; preserves the raw image."""
import argparse, hashlib, json, re, subprocess, sys, time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'kit/MoonRayForModo/python'))
from moonray_modo import native,rdla,denoising
parser=argparse.ArgumentParser();parser.add_argument('runtime',type=Path);args=parser.parse_args()
runtime=native.find_runtime(args.runtime)
out=root/'test-results'/('adaptive-'+time.strftime('%Y%m%d-%H%M%S'));out.mkdir(parents=True)
def run(argv,name):
    result=subprocess.run([str(x) for x in argv],env=native.environment(runtime),cwd=out,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
    text=result.stdout.decode('utf-8',errors='replace');(out/(name+'.log')).write_text(text,encoding='utf-8')
    if result.returncode: raise RuntimeError(name+' failed: '+text[-4000:])
    return text
image=out/'image.exr';guides={k:str(out/(k+'.exr')) for k in ('albedo','normal')}
scene={'camera':{'matrix':[1,0,0,0,0,1,0,0,0,0,1,0,0,0,4,1],'focal_mm':50,'film_mm':36},
 'materials':{'red':{'color':[.7,.03,.02],'roughness':.3}},'lights':[],
 'meshes':[{'name':'Adaptive check','vertices':[[-1,-1,0],[1,-1,0],[1,1,0],[-1,1,0]],'faces':[[0,1,2,3]],'material':'red'}],
 'render_settings':{'sampling_mode':2,'min_adaptive_samples':16,'max_adaptive_samples':64,'target_adaptive_error':1.5,'light_sampling_mode':1},
 'aovs':['sample_count'],'_denoise_guides':guides}
source=out/'scene.rdla';source.write_text(rdla.scene_text(scene,128,128,2,1,str(image)),encoding='utf-8')
log=run([runtime/'moonray.exe']+native.arguments(source,image,4,'xpu')+['-info'],'render')
assert 'GPU: Setup complete' in log and 'falling back' not in log.lower()
assert 'Pixels at max adaptive samples' in log
raw=hashlib.sha256(image.read_bytes()).hexdigest()
report={'runtime':str(runtime),'raw_sha256':raw,'engines':{}}
for engine in ('optix','oidn_cpu'):
    for i,(program,argv,output) in enumerate(denoising.jobs(runtime,image,out/engine,engine,guides)):
        run([program]+argv,engine+'-'+str(i));assert output.stat().st_size>16
    stats=run([runtime/'oiiotool.exe','--info','-v','--stats',output],engine+'-stats')
    assert re.search(r'128 x\s+128, 3 channel',stats)
    assert 'Stats NanCount: 0 0 0' in stats and 'Stats InfCount: 0 0 0' in stats and 'Constant: No' in stats
    report['engines'][engine]={'output':str(output),'finite_nonconstant':True}
assert raw==hashlib.sha256(image.read_bytes()).hexdigest()
report['passed']=True
(out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
