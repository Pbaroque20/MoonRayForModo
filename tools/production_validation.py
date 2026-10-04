"""Opt-in standalone production checks. Default: write a plan, run nothing."""
import argparse,copy,hashlib,json,math,os,re,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'kit/MoonRayForModo/python'),str(ROOT/'tests')]
from moonray_modo import native,rdla,recovery


def fixture(count):
    side=math.ceil(math.sqrt(count));start=[];end=[]
    for i in range(count):
        x=((i%side)+.5)/side*2-1;y=((i//side)+.5)/side*2-1
        scale=.8/side;a=list(rdla.IDENTITY);a[0]=a[5]=a[10]=scale;a[12]=x;a[13]=y
        b=list(a);angle=.55;b[0]=b[5]=math.cos(angle)*scale*1.4;b[1]=math.sin(angle)*scale*1.4;b[4]=-b[1]
        start.append(a);end.append(b)
    return {'camera':{'matrix':[1,0,0,0,0,1,0,0,0,0,1,0,0,0,4,1],'focal_mm':50,'film_mm':36},
       'materials':{'':{'color':[.5,.2,.8],'roughness':.3}},
       'meshes':[{'identity':'prototype','name':'Shared triangles','vertices':[[-1,-1,0],[1,-1,0],[0,1,0]],'faces':[[0,1,2]],
                  'matrix':rdla.IDENTITY,'instances':start,'instances_close':end,'instance_transform_motion':True,
                  'instance_ids':['replica-'+str(i) for i in range(count)]}],
       'lights':[{'identity':'key','kind':'DistantLight','color':[1,1,1],'intensity':1,'matrix':rdla.IDENTITY}],
       'fps':24,'motion_steps':[-.25,.25],'_paired_instance_motion':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--run',action='store_true');parser.add_argument('--instances',type=int,default=10000)
    parser.add_argument('--timeout',type=float,default=600);parser.add_argument('--cancel-after',type=float,default=3)
    parser.add_argument('--case',choices=('all','unit','inventory','shared','cancel','recovery'),default='all')
    args=parser.parse_args()
    if not 1<=args.instances<=1000000 or args.timeout<=0 or args.cancel_after<=0:parser.error('Invalid limits')
    folder=args.output.resolve()
    if folder.exists() and any(folder.iterdir()):parser.error('Choose an empty output directory')
    folder.mkdir(parents=True,exist_ok=True)
    cases=['unit','inventory','shared','cancel','recovery'] if args.case=='all' else [args.case]
    report={'status':'not_run','cases':{name:{'status':'not_run'} for name in cases},
       'manual_required':['Modo procedural/effect reference images','Native light links and environment graphs',
         'Simultaneous Cryptomatte categories and volume coverage (not implemented)',
         'Host cancellation during capture','Real production scenes with external assets',
         'OCIO/LUT reference color chart','Clean second Windows machine with Modo 16.1v9'],
       'limits':'Standalone synthetic checks are not production certification or a clean-machine test.'}
    report_path=folder/'report.json'
    def save():report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    save()
    if not args.run:print('Prepared only:',report_path);return
    runtime=native.find_runtime(args.runtime);env=native.environment(runtime)
    env['PATH']=str(runtime)+os.pathsep+str(Path(os.environ.get('SystemRoot','C:/Windows'))/'System32')
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    def run(command,log,timeout=None):
        with (folder/log).open('w',encoding='utf-8') as stream:
            process=subprocess.Popen([str(v) for v in command],env=env,stdout=stream,stderr=subprocess.STDOUT,creationflags=flags)
            try:code=process.wait(timeout=timeout or args.timeout)
            except BaseException:process.kill();process.wait(timeout=30);raise
        if code:raise RuntimeError('Exit '+str(code)+'; see '+log)
    def inspect(image):
        result=subprocess.run([str(runtime/'oiiotool.exe'),'--stats',str(image)],env=env,capture_output=True,text=True,timeout=60,creationflags=flags)
        (folder/(image.stem+'-stats.txt')).write_text(result.stdout+result.stderr,encoding='utf-8')
        if result.returncode:raise RuntimeError('EXR decode failed: '+str(image))
        for kind in ('NanCount','InfCount'):
            match=re.search(r'Stats '+kind+r':([^\n]+)',result.stdout)
            if not match or any(float(v) for v in re.findall(r'\d+(?:\.\d+)?',match.group(1))):raise RuntimeError('Missing/nonfinite EXR statistics: '+kind)
    def scene_file(value,name,samples=2,resolution=128):
        image=folder/(name+'.exr');path=folder/(name+'.rdla')
        path.write_text(rdla.scene_text(value,resolution,resolution,samples,.15,str(image)),encoding='utf-8')
        return path,image
    for name in cases:
        begin=time.monotonic()
        try:
            if name=='unit':
                run([sys.executable,'-m','unittest','discover','-s',ROOT/'tests','-p','test_compatibility_0321.py'],'unit.log')
            elif name=='inventory':
                manifest=json.loads((runtime/'build-manifest.json').read_text(encoding='utf-8'))
                for key,entry in manifest.items():
                    path=(runtime/key).resolve();path.relative_to(runtime)
                    if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:raise RuntimeError('Runtime hash mismatch: '+key)
                report['cases'][name]['files']=len(manifest)
            else:
                if not native.supports_paired_instance_motion(runtime):raise RuntimeError('Runtime lacks verified paired-transform capability')
                value=fixture(args.instances)
                if name=='shared':
                    source,image=scene_file(value,name)
                    for mode in ('scalar','vector','xpu'):
                        output=image.with_name('shared-'+mode+'.exr')
                        run([runtime/'moonray.exe',*native.arguments(source,output,0,mode)],'shared-'+mode+'.log')
                        inspect(output)
                        if mode=='xpu' and native.execution_status((folder/'shared-xpu.log').read_text(encoding='utf-8',errors='replace'))!='XPU active (NVIDIA GPU + CPU)':raise RuntimeError('XPU execution not confirmed; CPU fallback is not an XPU pass')
                else:
                    value['recovery']={'enabled':True,'resume':True,'minutes':.1} if name=='recovery' else {'enabled':False}
                    value['render_settings']={'sampling_mode':0}
                    destination=folder/(name+'.exr')
                    if name=='recovery':value['_recovery']=recovery.prepare(value,destination,256,256,64,.15,runtime)
                    source,image=scene_file(value,name,64,256)
                    with (folder/(name+'-interrupted.log')).open('w',encoding='utf-8') as log:
                        process=subprocess.Popen([str(runtime/'moonray.exe'),*native.arguments(source,image,0,'vector')],env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
                        try:
                            if name=='recovery':
                                checkpoint=Path(value['_recovery']['file']);previous=None;stable=0
                                while time.monotonic()-begin<args.timeout and process.poll() is None:
                                    state=(checkpoint.stat().st_size,checkpoint.stat().st_mtime_ns) if checkpoint.exists() else None
                                    stable=stable+1 if state and state==previous and state[0]>32 else 0;previous=state
                                    if stable>=5:break
                                    time.sleep(.2)
                                if stable<5:raise RuntimeError('No stable checkpoint before timeout/completion')
                            else:time.sleep(args.cancel_after)
                            if process.poll() is not None:raise RuntimeError('Render completed before cancellation; increase workload')
                            killed=time.monotonic();process.kill();process.wait(timeout=30)
                            report['cases'][name]['kill_seconds']=time.monotonic()-killed
                        finally:
                            if process.poll() is None:process.kill();process.wait(timeout=30)
                    if name=='recovery':
                        inspect(checkpoint);value.pop('_recovery',None)
                        value['_recovery']=recovery.prepare(value,destination,256,256,64,.15,runtime)
                        if not value['_recovery']['resume']:raise RuntimeError('Recovery did not select checkpoint')
                        source,image=scene_file(value,name,64,256)
                        run([runtime/'moonray.exe',*native.arguments(source,image,0,'vector')],'resume.log');inspect(image)
                    else:
                        source,image=scene_file(value,'after-cancel',2,64)
                        run([runtime/'moonray.exe',*native.arguments(source,image,0,'vector')],'after-cancel.log');inspect(image)
            report['cases'][name]['status']='passed'
        except Exception as exc:report['cases'][name].update(status='failed',reason=str(exc))
        report['cases'][name]['seconds']=time.monotonic()-begin;save()
    report['status']='standalone_checks_passed' if all(v['status']=='passed' for v in report['cases'].values()) else 'failed'
    save();print(report_path)
    if report['status']=='failed':raise SystemExit(1)

if __name__=='__main__':main()
