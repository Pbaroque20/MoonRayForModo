"""Render nested instancing against explicit flattened transforms (linear alpha)."""
import argparse,json,struct,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import native,rdl_import,rdla
p=argparse.ArgumentParser();p.add_argument('runtime');a=p.parse_args()
runtime=Path(a.runtime).resolve();out=Path('test-results/rdl-nested-transforms').resolve();out.mkdir(parents=True,exist_ok=True)
def matrix(x):
 m=rdl_import.IDENTITY[:];m[12]=x;return m
def mat(x):return rdla.matrix(matrix(x))
def render(name,body):
 path=out/(name+'.rdla');image=out/(name+'.exr')
 path.write_text('local camera=PerspectiveCamera("camera") { ["node_xform"]=Mat4(1,0,0,0,0,1,0,0,0,0,1,0,0,0,5,1) }\n'+
  'local paint=DwaBaseMaterial("paint") {}\n'+body+'\nSceneVariables { ["camera"]=camera,["layer"]=layer,["image_width"]=64,["image_height"]=64,["pixel_samples"]=2,["sampling_mode"]=0,["two_stage_output"]=false,["max_depth"]=1 }',encoding='utf-8')
 r=subprocess.run([str(runtime/'moonray.exe')]+native.arguments(path,image,threads=1,mode='scalar'),env=native.environment(runtime),capture_output=True,text=True,timeout=90)
 (out/(name+'.log')).write_text(r.stdout+r.stderr,encoding='utf-8');assert r.returncode==0,(name,r.returncode)
 pfm=out/(name+'.pfm')
 subprocess.run([str(runtime/'oiiotool.exe'),str(image),'--ch','A,A,A','-o',str(pfm)],env=native.environment(runtime),check=True,capture_output=True,timeout=30)
 with pfm.open('rb') as f:
  assert f.readline().strip()==b'PF';w,h=map(int,f.readline().split());scale=float(f.readline());data=f.read()
 values=struct.unpack(('<' if scale<0 else '>')+str(w*h*3)+'f',data)
 return values
mesh='RdlMeshGeometry("mesh") { ["vertex_list_0"]={Vec3(-.4,-.4,0),Vec3(.4,-.4,0),Vec3(0,.4,0)},["face_vertex_count"]={3},["vertices_by_index"]={0,1,2},["node_xform"]=%s }'
results={}
for use in (True,False):
 key='reference_on' if use else 'reference_off'
 source='local mesh='+mesh%mat(.1)+'\nlocal inner=RdlInstancerGeometry("inner") { ["method"]=2,["references"]={mesh},["use_reference_xforms"]=true,["xform_list"]={'+mat(.2)+'},["node_xform"]='+mat(.3)+' }\nlocal outer=RdlInstancerGeometry("outer") { ["method"]=2,["references"]={inner},["xform_list"]={'+mat(.4)+'},["node_xform"]='+mat(.5)+',["use_reference_xforms"]='+str(use).lower()+' }\nGeometrySet("geos") {mesh,inner,outer}\nlocal layer=Layer("layer") {{mesh,"",paint},{inner,""},{outer,""}}'
 ref=render(key,source)
 r=subprocess.run([str(runtime/'modo_rdl_import.exe'),str(out/(key+'.rdla')),str(runtime)],env=native.environment(runtime),capture_output=True,text=True,timeout=60)
 assert r.returncode==0,r.stderr
 document=json.loads(r.stdout.rsplit('@@MODO_RDL_JSON',1)[1])
 plan=rdl_import.plan(document,str(out/(key+'.rdla')))
 expected=plan['meshes'][0]['matrix'][12]
 flat=render(key+'_flat','local mesh='+mesh%mat(expected)+'\nGeometrySet("geos") {mesh}\nlocal layer=Layer("layer") {{mesh,"",paint}}')
 err=sum(abs(x-y) for x,y in zip(ref,flat))/len(ref)
 results[key]={'expected_translation':expected,'mean_alpha_error':err,'coverage':sum(ref)/3}
 assert sum(ref)>0,'Empty reference render'
 assert err<.001,results
# Audit source-only versus instancer-only material assignment independently of transforms.
outer_only=source.replace('{mesh,"",paint},{inner,""},{outer,""}', '{mesh,""},{inner,""},{outer,"",paint}')
coverage=render('instancer_material_only',outer_only)
results['instancer_material_only']={'coverage':sum(coverage)/3}
assert sum(coverage)==0,'Runtime instancer-only material semantics changed'
(out/'report.json').write_text(json.dumps(results,indent=2),encoding='utf-8');print(json.dumps(results))
