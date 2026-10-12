"""Validate the negative-index crash fixture against an explicit candidate runtime."""
import argparse,json,struct,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'kit/MoonRayForModo/python'))
from moonray_modo import native
p=argparse.ArgumentParser();p.add_argument('runtime',type=Path);a=p.parse_args();runtime=a.runtime.resolve()
out=root/'test-results/native-index-render';out.mkdir(parents=True,exist_ok=True)
source=(root/'tests/fixtures/negative_instance_reference.rdla').read_text(encoding='utf-8');images={}
for name,text in [('negative',source),('valid',source.replace('["ref_indices"]={-1}','["ref_indices"]={0}'))]:
 path=out/(name+'.rdla');image=out/(name+'.exr');path.write_text(text,encoding='utf-8')
 result=subprocess.run([str(runtime/'moonray.exe')]+native.arguments(path,image,threads=1,mode='scalar'),env=native.environment(runtime),capture_output=True,text=True,timeout=90)
 (out/(name+'.log')).write_text(result.stdout+result.stderr,encoding='utf-8')
 assert result.returncode==0,(name,result.returncode)
 pfm=out/(name+'.pfm')
 subprocess.run([str(runtime/'oiiotool.exe'),str(image),'--ch','A,A,A','-o',str(pfm)],env=native.environment(runtime),capture_output=True,check=True,timeout=30)
 with pfm.open('rb') as f:
  assert f.readline().strip()==b'PF';w,h=map(int,f.readline().split());scale=float(f.readline());images[name]=struct.unpack(('<' if scale<0 else '>')+str(w*h*3)+'f',f.read())
assert sum(images['valid'])>0,'Empty control'
error=sum(abs(x-y) for x,y in zip(images['negative'],images['valid']))/len(images['valid'])
assert error==0,error
report={'ok':True,'runtime':str(runtime),'mean_alpha_error':error,'control_coverage':sum(images['valid'])/3}
(out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
