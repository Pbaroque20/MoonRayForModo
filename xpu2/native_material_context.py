"""Diagnostic helping with explicit preservation of shading attribute context."""
from . import native_material_help as help
from .native_gpu_paths import once
adapter=help.adapter
cpp=help.cpp
queue=help.queue
profile=help.profile
cuda=help.cuda
ispc=help.ispc
multisampler=help.multisampler

def header(text):
    text=help.header(text)
    text=once(text,'#include <moonray/rendering/rndr/RenderDriver.h>', '#include <moonray/rendering/rndr/RenderDriver.h>\n#include <moonray/rendering/shading/ShadingTLState.h>')
    return once(text,
        'struct Guard { Guard(){helpingMaterial=true;++activeCpu;}~Guard(){--activeCpu;helpingMaterial=false;} } guard;',
        r"""struct Guard {
        moonray::shading::TLState* shading;const int* offsets;
        explicit Guard(moonray::pbr::TLState* tls):shading(tls->mTopLevelTls->mShadingTls.get()),offsets(shading->mAttributeOffsets){
            shading->mAttributeOffsets=nullptr;helpingMaterial=true;++activeCpu;
        }
        ~Guard(){shading->mAttributeOffsets=offsets;--activeCpu;helpingMaterial=false;}
    } guard(tls);""")
