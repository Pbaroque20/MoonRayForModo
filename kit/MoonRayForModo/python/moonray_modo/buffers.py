"""Display-only conversion of linear render buffers; EXR values remain unchanged."""
from . import options


def conversion(key, source, destination, display=None):
    if key!='beauty' and key not in options.AOVS: raise ValueError('Unknown preview buffer: '+key)
    # Drop coverage alpha before any transform or PNG encoding. Never divide
    # RGB (which already includes the environment) by silhouette coverage.
    args=['--no-autopremult',str(source),'--fixnan','black']
    if key in ('alpha','depth','wireframe','sample_count'):
        args += ['--ch','0,0,0']
    elif key=='uv':
        args += ['--ch','0,1,B=0']
    else:
        args += ['--ch','0,1,2']
    if key in ('normal','geometric_normal'):
        args += ['--mulc','0.5','--addc','0.5']
    elif key in ('depth','sample_count'):
        args += ['--rangecompress']
    elif key=='position':
        args += ['--rangecompress','--mulc','0.5','--addc','0.5']
    elif key not in ('alpha','uv','wireframe'):
        from .display import arguments
        args += arguments(display or {})
    return args+['-d','uint8','-o',str(destination)]
