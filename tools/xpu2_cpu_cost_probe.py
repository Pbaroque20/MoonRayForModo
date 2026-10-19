"""Sample native CPU shading costs with reference images and same-binary off controls."""
import argparse,csv,ctypes,json,math,statistics,subprocess,sys,time
from ctypes import wintypes
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file,inventory,verify
from xpu2.images import read_rgba,compare_rgba
from xpu2_baseline import environment
from xpu2_repeatability import successful,gpu_identity

def renderer_pids():
 # Lightweight process snapshot during a frame; no recurrent PowerShell launch.
 class Entry(ctypes.Structure):
  _fields_=[('size',wintypes.DWORD),('usage',wintypes.DWORD),('pid',wintypes.DWORD),('heap',ctypes.c_size_t),('module',wintypes.DWORD),('threads',wintypes.DWORD),('parent',wintypes.DWORD),('priority',wintypes.LONG),('flags',wintypes.DWORD),('name',wintypes.WCHAR*260)]
 k=ctypes.WinDLL('kernel32',use_last_error=True)
 k.CreateToolhelp32Snapshot.argtypes=[wintypes.DWORD,wintypes.DWORD];k.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
 k.Process32FirstW.argtypes=[wintypes.HANDLE,ctypes.POINTER(Entry)];k.Process32NextW.argtypes=k.Process32FirstW.argtypes
 k.CloseHandle.argtypes=[wintypes.HANDLE]
 handle=k.CreateToolhelp32Snapshot(2,0)
 if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
 try:
  e=Entry();e.size=ctypes.sizeof(e);ok=k.Process32FirstW(handle,ctypes.byref(e));pids=[]
  while ok:
   if e.name.lower()=='moonray.exe':pids.append(e.pid)
   ok=k.Process32NextW(handle,ctypes.byref(e))
  return pids
 finally:k.CloseHandle(handle)

def fixtures(base,out,runtime):
 # Local generated asset: no network, no user textures or scenes modified.
 texture=out/'pattern.ppm';size=512
 pixels=bytearray()
 for y in range(size):
  for x in range(size):
   checker=((x//17+y//23)%2)*90
   pixels.extend((40+(x*3+y)%120,45+checker,50+(x+y*5)%130))
 texture.write_bytes(('P6\n%d %d\n255\n'%(size,size)).encode()+pixels)
 tx=out/'pattern.tx';env=environment(runtime,out)
 subprocess.run([str(runtime/'maketx.exe'),str(texture),'-o',str(tx)],env=env,cwd=out,check=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
 source=base.read_text();source+='\nSceneVariables {["image_width"]=384,["image_height"]=216}\n'
 paths={};p=out/'diffuse.rdla';p.write_text(source);paths['diffuse']=p
 # Nine meshes instead of one, using the same tested indexed sphere geometry.
 source=source.replace('do\n  local geometry = RdlMeshGeometry("/modo/mesh/0")', 'for gx=-1,1 do for gy=-1,1 do\n  local geometry = RdlMeshGeometry("/cost/mesh/"..gx.."/"..gy)')
 source=source.replace('["node_xform"] = Mat4(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)', '["node_xform"] = Mat4(0.55,0,0,0,0,0.55,0,0,0,0,0.55,0,gx*1.15,gy*1.15,0,1)')
 source=source.replace('table.insert(geometries, geometry)\nend', 'table.insert(geometries, geometry)\nend end')
 source=source.replace('0, 0, 4, 1)', '0, 0, 7, 1)')
 # Ground below the lower row; leave its material in the same stress hierarchy.
 source=source.replace(',-1,', ',-1.8,')
 prefix='''
local costMats={}
for i=1,8 do
 costMats[i]=DwaBaseMaterial('/cost/base/'..i){
  ['albedo']=Rgb(0.12+i*0.065,0.35,0.7-i*0.055), ['metallic']=(i%3)*0.25,
  ['roughness']=0.15+i*0.07, ['diffuse_roughness']=0.5,
  ['show_clearcoat']=true,['clearcoat']=0.6,['clearcoat_roughness']=0.18
 }
end
local costLayer=costMats[1]
for i=2,8 do costLayer=DwaLayerMaterial('/cost/layer/'..i){['material_A']=costMats[i],['material_B']=costLayer,['mask']=0.35} end
for i,a in ipairs(assignments) do a[3]=costLayer end
'''
 anchor='local layer = Layer("/modo/layer")(assignments)'
 for name,textured,many in [('layered',False,False),('textured',True,False),('many_lights',True,True),('many_adaptive',True,True)]:
  extra=prefix
  if textured:
   extra+='\nfor i=1,8 do\n'
   for attr in ('albedo','roughness','clearcoat_roughness','diffuse_roughness'):
    extra+="local tex=ImageMap('/cost/map/"+attr+"/'..i){['texture']='"+tx.as_posix()+"',['scale']=Vec2(1+i*0.2,1+i*0.13)}\ncostMats[i]{['"+attr+"']=bind(tex)}\n"
   extra+='end\n'
  if many:
   extra+='''
for i=0,63 do
 local x=(i%8-3.5)*0.7
 local y=(math.floor(i/8)-3.5)*0.7
 table.insert(lights,RectLight('/cost/light/'..i){['node_xform']=Mat4(1,0,0,0,0,1,0,0,0,0,1,0,x,y,3,1),['intensity']=0.16,['width']=0.3,['height']=0.3,['sidedness']=2})
end
LightSet('/modo/lightSet')(lights)
'''
  p=out/(name+'.rdla');p.write_text(source.replace(anchor,extra+'\n'+anchor));paths[name]=p
  if name=='many_adaptive':p.write_text(p.read_text()+'\nSceneVariables {["light_sampling_mode"]=1,["light_sampling_quality"]=0.5}\n')
 return paths

def cost_rows(path):
 result={}
 with path.open(newline="") as stream:rows=list(csv.DictReader(stream))
 for r in rows:
  if int(r['errors']) or int(r['active']):raise ValueError('Unbalanced or nested CPU scopes')
  if any(int(r[k])<0 for k in ('calls','lanes','sampled_calls','sampled_lanes','exclusive_ns')):raise ValueError('Negative CPU counter')
  if int(r['sampled_calls'])>int(r['calls']) or int(r['sampled_lanes'])>int(r['lanes']):raise ValueError('Sample counts exceed total work')
  s=result.setdefault(r['stage'],dict(calls=0,lanes=0,sampled_calls=0,sampled_lanes=0,exclusive_ns=0))
  for k in s:s[k]+=int(r[k])
  s['empty_pair_ns']=int(r['empty_pair_ns'])
 for s in result.values():
  s['ns_per_active_lane']=s['exclusive_ns']/s['sampled_lanes'] if s['sampled_lanes'] else None
  s['estimated_total_seconds']=s['ns_per_active_lane']*s['lanes']/1e9 if s['sampled_lanes'] else None
 return result

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for k in ('build','reference','scene','output'):p.add_argument('--'+k,type=Path,required=True)
 p.add_argument('--resume',type=Path,help='Resume missing cases from a preserved report; completed source and image checks are required')
 p.add_argument('--fixtures',default='diffuse,layered,textured,many_adaptive')
 a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
 report={'status':'incomplete','threads':1,'bridge_enabled':False,'runs':[]}
 def save():(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
 try:
  build=a.build.resolve();rt=build/'runtime';ref=a.reference.resolve();b=json.loads((build/'report.json').read_text())
  assert b['status']=='built' and digest_file(rt/'librendering_rndr.dll')==b['dll_sha256']
  pinned={**b['source_hashes'],**b['native_hashes'],str(Path(__file__)):digest_file(Path(__file__))}
  for f,h in pinned.items():
   if digest_file(Path(f))!=h:raise ValueError('Source drift '+f)
  held={str(r):inventory(r) for r in (rt,ref)};report['gpu']=gpu_identity();report['source_hashes']=pinned
  if a.resume:
   prior=json.loads(a.resume.read_text());prior_dir=a.resume.resolve().parent
   if prior.get('threads')!=1 or prior.get('bridge_enabled') is not False or prior.get('gpu')!=report['gpu']:raise ValueError('Resume configuration differs')
   for f,h in prior['source_hashes'].items():
    target=Path(f)
    if target.resolve()==Path(__file__).resolve():target=prior_dir/'probe_at_capture.py'
    if digest_file(target)!=h:raise ValueError('Resume source drift '+str(target))
   paths={k:Path(v['path']) for k,v in prior['fixtures'].items()}
   for k,v in paths.items():
    if digest_file(v)!=prior['fixtures'][k]['sha256']:raise ValueError('Resume fixture drift')
   for row in prior['runs']:
    if not row['execution']['passed'] or row.get('comparison',{}).get('exactly_different_pixels')!=0:raise ValueError('Unqualified prior image')
    row['artifact_folder']=str(prior_dir/(row['fixture']+'-'+row['label']))
   report['runs']=prior['runs'];report['resumed_from']={'path':str(a.resume.resolve()),'sha256':digest_file(a.resume),'reason':prior.get('error')}
  else:paths=fixtures(a.scene.resolve(),out,rt)
  report['fixtures']={k:{'path':str(v),'sha256':digest_file(v)} for k,v in paths.items()}
  assets={str(v):digest_file(v) for v in paths.values()}
  for v in (next(iter(paths.values())).parent).glob('pattern.*'):assets[str(v)]=digest_file(v)
  report['asset_hashes']=assets
  for name in a.fixtures.split(','):
   baseline=None
   existing=next((r for r in report['runs'] if r['fixture']==name and r['label']=='reference'),None)
   if existing:
    ref_folder=Path(existing['artifact_folder']);baseline=read_rgba(ref,ref_folder/'beauty.exr',out,'resume-'+name,environment(ref,out))
   # Bracketing off controls, two independent sampling densities/seeds.
   for label,rate,seed in [('reference',0,0),('off_before',0,0),('sample64',64,173),('sample16',16,761),('off_after',0,0)]:
    if any(r['fixture']==name and r['label']==label for r in report['runs']):continue
    folder=out/(name+'-'+label);folder.mkdir();runtime=ref if label=='reference' else rt;env=environment(runtime,folder)
    if rate:env.update(XPU2_CPU_COST=str(folder/'cpu.csv'),XPU2_CPU_COST_RATE=str(rate),XPU2_CPU_COST_SEED=str(seed))
    if renderer_pids():raise ValueError('Competing renderer active')
    print(name,label,flush=True)
    with (folder/'render.log').open('w') as log:
     proc=subprocess.Popen([str(runtime/'moonray.exe'),'-in',str(paths[name]),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads','1','-info','-stats',str(folder/'stats.csv')],env=env,cwd=folder,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
     deadline=time.monotonic()+600;competition=set()
     try:
      while proc.poll() is None:
       competition.update(pid for pid in renderer_pids() if pid!=proc.pid)
       if time.monotonic()>deadline:raise TimeoutError('Render timeout')
       try:proc.wait(timeout=.25)
       except subprocess.TimeoutExpired:pass
     finally:
      if proc.poll() is None:proc.kill();proc.wait(timeout=10)
     if competition:raise ValueError('Timing contaminated by renderer PIDs '+str(sorted(competition)))
    if renderer_pids():raise ValueError('Timing contaminated')
    log=(folder/'render.log').read_text(errors='replace');stats=(folder/'stats.csv').read_text(errors='replace') if (folder/'stats.csv').exists() else ''
    row={'fixture':name,'label':label,'artifact_folder':str(folder),'rate':rate,'seed':seed,'execution':successful('xpu',1,proc.returncode,log,stats,(folder/'beauty.exr').exists())};report['runs'].append(row);save()
    if not row['execution']['passed']:raise ValueError('Render failed '+name+' '+label)
    errors=[line for line in log.splitlines() if any(x in line.lower() for x in ('rdla error','could not open','unable to open','not a valid attribute','unknown attribute'))]
    if errors:raise ValueError(str(errors[:5]))
    rgba=read_rgba(runtime,folder/'beauty.exr',folder,'raw',env)
    if baseline is None:baseline=rgba
    row['comparison']=compare_rgba(baseline,rgba)
    if row['comparison']['exactly_different_pixels']:raise ValueError('CPU probe changed image')
    if rate:
     row['cpu']=cost_rows(folder/'cpu.csv')
     if not sum(s['sampled_lanes'] for s in row['cpu'].values()):raise ValueError('CPU probe inactive')
    save()
  for f,h in assets.items():
   if digest_file(Path(f))!=h:raise ValueError('Fixture asset drift '+f)
  for r in (rt,ref):verify(r,held[str(r)])
  for f,h in pinned.items():
   if digest_file(Path(f))!=h:raise ValueError('Sources changed during test '+f)
  report['status']='passed'
 except Exception as e:
  import traceback
  report['error']=str(e);report['traceback']=traceback.format_exc()
 save();print(report['status'],report.get('error',''),flush=True)
 return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
