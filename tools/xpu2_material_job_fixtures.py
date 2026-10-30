from pathlib import Path
import argparse,json,hashlib
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=False)
s=a.source.read_text();assert s.count('["diffuse_roughness"]=0,')==1
rough=s.replace('["diffuse_roughness"]=0,','["diffuse_roughness"]=0.6,')
anchor='local layer = Layer("/modo/layer")(assignments)';assert s.count(anchor)==1
mixed=rough.replace(anchor,'''local nativeMetal=UsdPreviewSurface("/xpu2/native-metal") { ["diffuseColor"]=Rgb(0.75,0.4,0.15), ["metallic"]=1, ["roughness"]=0.3 }
assignments[#assignments][3]=nativeMetal
'''+anchor)
for name,text in [('rough-transmission',rough),('mixed-larger',mixed+'\nSceneVariables { ["image_width"]=512,["image_height"]=288 }\n'),('packet-bound',s+'\nSceneVariables { ["bsdf_samples"]=4 }\n')]:
 f=a.output/(name+'.rdla');f.write_text(text)
report={'source':str(a.source.resolve()),'source_sha256':hashlib.sha256(a.source.read_bytes()).hexdigest(),'files':{str(f.resolve()):hashlib.sha256(f.read_bytes()).hexdigest() for f in a.output.glob('*.rdla')}}
(a.output/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
