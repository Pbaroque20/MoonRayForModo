"""Deferred offline preview/export regressions. Does not launch Modo or render."""
import copy
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'kit/MoonRayForModo/python'))
from moonray_modo import background,buffers,display,rdla,options


def main():
    scene={'camera':{'matrix':rdla.IDENTITY,'focal_mm':50,'film_mm':36},'meshes':[],
           'environments':[{'kind':'constant','zenith':[.2,.4,.8],'intensity':1,'camera':True,'indirect':True,'reflection':True,'refraction':True}]}
    original=copy.deepcopy(scene)
    background.apply(scene,{})
    assert scene==original
    background.apply(scene,{'mode':'black'})
    assert not scene['environments'][0]['camera'] and scene['environments'][0]['indirect']
    background.apply(scene,{'mode':'color','color':'#804020'})
    camera=scene['environments'][-1]
    assert camera['camera'] and not any(camera[k] for k in ('indirect','reflection','refraction'))
    for key in ['beauty']+list(options.AOVS):
        scene['preview_buffer']=key;scene['preview_buffer_file']='buffer.exr'
        text=rdla.scene_text(scene)
        assert 'RenderOutput("/modo/preview/buffer")' in text
        args=buffers.conversion(key,'buffer.exr','preview.png')
        assert '--unpremult' not in args and '--premult' not in args
        assert '--ch' in args
        if key in ('normal','depth','alpha','uv','position','geometric_normal','wireframe'):
            assert '--colorconvert' not in args
        else: assert args.index('--ch')<args.index('--colorconvert')
        assert '/modo/preview/buffer' not in rdla.scene_text(scene,output_file='final.exr')
    assert '--mulc' in display.arguments({'exposure':1})
    try: display.values({'exposure':float('inf')})
    except ValueError: pass
    else: raise AssertionError('Invalid exposure accepted')
    print('Preview controls export checks passed. Qt lifecycle, native form refresh and render appearance still need validation.')

if __name__=='__main__': main()
