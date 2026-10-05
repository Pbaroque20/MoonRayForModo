"""Value-state comparison for graph properties, independent of Qt."""
import math
from .node_defaults import value as declared_default

DEFAULT_COLOR='#000000'
EDITED_COLOR='#00ffff'

def default(spec,kind=None,key=None):
    return declared_default(spec)

def equal(a,b):
    if isinstance(a,bool) or isinstance(b,bool):return type(a) is type(b) and a==b
    if isinstance(a,(int,float)) and isinstance(b,(int,float)):
        # Controls expose six decimals. Avoid marking their rounding as an edit.
        return math.isfinite(a) and math.isfinite(b) and math.isclose(a,b,rel_tol=0.0,abs_tol=5e-7)
    if isinstance(a,(list,tuple)) and isinstance(b,(list,tuple)):
        return len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
    if isinstance(a,dict) and isinstance(b,dict):
        return a.keys()==b.keys() and all(equal(a[k],b[k]) for k in a)
    return type(a) is type(b) and a==b

def color(value,spec,kind=None,key=None,connected=False):
    return EDITED_COLOR if connected or not equal(value,default(spec,kind,key)) else DEFAULT_COLOR
