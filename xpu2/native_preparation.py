"""Reuse invariant lobe packing and group replay checks without weakening identity."""
from pathlib import Path
from . import native_window as base
from .native_gpu_paths import once
HERE=Path(__file__).resolve().parent
adapter=base.adapter
cpp=base.cpp
queue=base.queue
profile=base.profile
cuda=base.cuda
shadow_header=base.shadow_header
driver=base.driver
multisampler=base.multisampler
bundled=base.bundled

def header(text):
    text=base.header(text)
    text=once(text,'inline void windowReset(){','inline void preparationReset();inline void preparationFinish();\ninline void windowReset(){preparationReset();')
    text=once(text,'inline void windowFinish(){','inline void windowFinish(){preparationFinish();')
    text=once(text,'extern "C" void CPP_gpuEarlySubmitGroup(const float* input,','extern "C" void CPP_gpuEarlySubmitGroupWindow(const float* input,')
    return text+'\n'+(HERE/'native_preparation.inc').read_text()

def ispc(text,bsdf_header):
    text=base.ispc(text,bsdf_header)
    start=text.index('inline uniform bool xpu2PrepareLobe(')
    end=text.index('    return xpu2Prepared;',start)
    part=text[start:end]
    first=part.index('                        xpu2Input[b]=')
    last=part.index('\n                    }',first)
    assignments=part[first:last]
    random='xpu2Input[b+11]=extract(xpu2Sample[0],lane);xpu2Input[b+12]=extract(xpu2Sample[1],lane);'
    if assignments.count(random)!=1:raise ValueError('Sample assignment drift')
    common=assignments.replace(random,'').replace('xpu2Input[','xpu2Common[')
    anchor='            for(uniform int j=0;j<reduce_max(lobeSampleCount);++j){'
    init='            uniform bool xpu2ReusePacking=CPP_gpuReusePacking();\n            uniform float xpu2Common[192];\n            if(xpu2ReusePacking){\n                for(uniform int k=0;k<192;++k)xpu2Common[k]=0.f;\n                foreach_active(lane){\n                    uniform int b=lane*24;\n'+common+'\n                }\n            }\n'
    part=once(part,anchor,init+anchor)
    replacement='                        if(xpu2ReusePacking){\n                            for(uniform int k=0;k<24;++k)xpu2Input[b+k]=xpu2Common[b+k];\n                            '+random+'\n                        }else{\n'+assignments+'\n                        }'
    part=once(part,assignments,replacement)
    return text[:start]+'extern "C" uniform bool CPP_gpuReusePacking();\n'+part+text[end:]
