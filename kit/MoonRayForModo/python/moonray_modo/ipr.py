"""Preview-only quality limits; never mutate scene-owned/final settings."""
from . import options


def prepare(scene, width, height, sample_grid, width_cap=160, sample_cap=1, error=100.0):
    if width_cap not in (80,160,240) or sample_cap not in (1,4,16):
        raise ValueError('Invalid IPR quality preset')
    if not 0.1<=float(error)<=1000:
        raise ValueError('IPR adaptive error must be between 0.1 and 1000')
    settings=options.render_values(scene.get('render_settings',{}))
    original_cap=settings['max_adaptive_samples'] if settings['sampling_mode']==2 else int(sample_grid)**2
    cap=max(1,min(sample_cap,original_cap))
    # MoonRay clamps adaptive sampling to >=2 internally. Uniform grid 1 is
    # required for a genuine single-sample preview.
    settings.update(sampling_mode=0 if cap==1 else 2,min_adaptive_samples=1 if cap==1 else 2,
                    max_adaptive_samples=cap,
                    target_adaptive_error=max(float(error),settings['target_adaptive_error']),
                    light_samples=1,bsdf_samples=1,bssrdf_samples=1)
    result=dict(scene,render_settings=settings,_ipr=True)
    # Cap both scene and normal preview width, so IPR never enlarges either.
    scale=min(1.0,float(width_cap)/max(1,width),float(scene['width'])/max(1,width))
    return result,max(16,round(width*scale)),max(16,round(height*scale))
