"""Linear beauty-only denoising; raw EXR/AOVs never enter a destructive operation."""
from pathlib import Path
ENGINES=('off','optix','oidn_cpu')
def settings(value):
    result={'engine':value.get('engine','off'),'preview':value.get('preview',True),'final':value.get('final',True)}
    if result['engine'] not in ENGINES or type(result['preview']) is not bool or type(result['final']) is not bool:
        raise ValueError('Invalid denoising settings')
    return result

def enabled(snapshot,final=False,linear=False):
    value=settings(snapshot.get('denoising',{}))
    return value['engine']!='off' and value['final' if final else 'preview'] and not linear and (final or snapshot.get('preview_buffer','beauty')=='beauty')

def sidecar(path):
    path=Path(path);return path.with_name(path.stem+'.denoised.exr')

def jobs(runtime,source,base,engine,guides):
    runtime=Path(runtime);base=Path(base)
    if engine not in ENGINES[1:]: raise ValueError('Choose a denoising engine')
    denoiser=runtime/'denoise.exe';oiio=runtime/'oiiotool.exe'
    if not denoiser.is_file() or not oiio.is_file(): raise ValueError('This runtime does not include the denoising tools')
    rgba=base.with_suffix('.denoise-input.exr');filtered=base.with_suffix('.denoise-filtered.exr');output=base.with_suffix('.denoised.exr')
    # Isolate four known channels: native denoiser must never receive a multi-AOV EXR.
    return [(oiio,['--no-autopremult',str(source),'--ch','R,G,B,A=1','-d','float','-o',str(rgba)],rgba),
        (denoiser,['-in',str(rgba),'-albedo',guides['albedo'],'-normals',guides['normal'],'-mode',engine,'-out',str(filtered)],filtered),
        (oiio,['--no-autopremult',str(filtered),'--ch','R,G,B','-d','float','-o',str(output)],output)]
