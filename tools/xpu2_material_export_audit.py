"""Identify the material emitted by the real kit serializer; no Modo or scene mutation."""
import argparse,copy,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file
from xpu2_baseline import fixture

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kit',type=Path,default=ROOT/'kit/MoonRayForModo')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(a.kit.resolve()/'python'))
    from moonray_modo import rdla
    cases={
        'ordinary':({},'UsdPreviewSurface'),
        'ordinary-metal':({'metallic':.5},'UsdPreviewSurface'),
        'opaque-diffuse-first-port':({'specular':[0.,0.,0.],'metallic':0.,'clearcoat':0.,'opacity':1.,'emission':[0.,0.,0.]},'UsdPreviewSurface'),
        'glass':({'transmission':.5},'DwaBaseMaterial'),
        'rough-diffuse':({'diffuse_roughness':.5},'DwaBaseMaterial'),
        'moonshine':({'shader':'DwaBaseMaterial'},'DwaBaseMaterial')}
    report=dict(status='incomplete',cases={},scope='Exporter branch checks, not measured user-scene frequency or GPU qualification')
    for name,(changes,expected) in cases.items():
        scene=fixture(16);scene['materials']['red'].update(changes)
        text=rdla.scene_text(scene,128,128,1)
        result=re.search(r'materials\["red"\] = (\w+)\(',text)
        if not result or result.group(1)!=expected:
            raise ValueError('Exporter selection changed '+name)
        file=out/(name+'.rdla');file.write_text(text)
        report['cases'][name]=dict(emitted=result.group(1),input_material=scene['materials']['red'],sha256=digest_file(file),path=str(file))
    # Pin every serializer module actually imported, including protected modules read-only.
    report['source_hashes']={str(Path(m.__file__).resolve()):digest_file(Path(m.__file__)) for k,m in tuple(sys.modules.items()) if k.startswith('moonray_modo') and getattr(m,'__file__',None)}
    report['status']='passed';(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v['emitted'] for k,v in report['cases'].items()}))
if __name__=='__main__':main()
