"""Bounded cross-block numeric prefetch; native integration order stays unchanged."""
from pathlib import Path
from . import native_efficiency as base
from .native_gpu_paths import once
HERE=Path(__file__).resolve().parent
adapter=base.adapter
cpp=base.cpp
queue=base.queue
profile=base.profile
cuda=base.cuda
shadow_header=base.shadow_header
driver=base.driver
ispc=base.ispc

def header(text):
    text=base.header(text)
    text=once(text,'extern "C" uint64_t CPP_gpuEarlySubmit(', 'extern "C" uint64_t CPP_gpuEarlySubmitRaw(')
    text=once(text,'extern "C" void CPP_gpuEarlySubmitGroup(', 'extern "C" void CPP_gpuEarlySubmitGroupRaw(')
    text=once(text,'inline void stageReset();', 'inline bool recordingWindow();inline void windowReset();inline void windowFinish();\ninline void stageReset();')
    text=once(text,'inline void stageReset(){','inline void stageReset(){windowReset();')
    text=once(text,'inline void stageFinish(){','inline void stageFinish(){windowFinish();')
    text=once(text,'    ++stageCalls;++activeCpu;', '    if(recordingWindow())return;\n    ++stageCalls;++activeCpu;')
    return text+'\n'+(HERE/'native_window.inc').read_text()

def multisampler(text):
    text=base.multisampler(text)
    text=once(text,'#include "LightSetSampler.isph"','#include "LightSetSampler.isph"\nextern "C" void CPP_gpuWindowReplayEnd();')
    anchor='uniform bool xpu2Staged=xpu2SubmitMaterial(pbrTls,bSampler,rs->mSubpixel,pv,sequenceID,xpu2Tokens,xpu2Prepared);'
    return once(text,anchor,anchor+'\n    CPP_gpuWindowReplayEnd();')

def bundled(text):
    text=once(text,'// Returns the number of BundledRadiance entries', '#include "BsdfSampler.isph"\n'+(HERE/'native_window.ispc.inc').read_text()+'\n// Returns the number of BundledRadiance entries')
    text=once(text,'const varying float *          uniform presences)', 'const varying float *          uniform presences,uniform uint64 xpu2Window)')
    anchor='    for (uniform uint32_t i = 0; i < numBlocks; ++i) {'
    text=once(text,anchor,anchor+r"""
        if(xpu2Window && i%CPP_gpuWindowSize()==0){
            uniform unsigned width=CPP_gpuWindowSize();
            for(uniform unsigned j=0;j<width && i+j<numBlocks;++j){
                CPP_gpuWindowRecord(xpu2Window,j);
                if((i+j+1)*VLEN<=numEntries)
                    xpu2WindowPrepare(this,pbrTls,rayStates[i+j],isects[i+j],bsdfs[i+j],presences[i+j]);
            }
            CPP_gpuWindowPublish(xpu2Window);
        }
""")
    anchor='        computeRadianceBsdfMultiSampler(this,'
    text=once(text,anchor,'        if(xpu2Window)CPP_gpuWindowReplay(xpu2Window,i%CPP_gpuWindowSize());\n'+anchor)
    call='    integrateBundled(this, pbrTls, shadingTls, numEntries, rayStates, isects, bsdfs, lightList, presences);'
    return once(text,call,'    uniform uint64 window=CPP_gpuWindowBegin(pbrTls);\n'+call.replace('presences);','presences,window);')+'\n    CPP_gpuWindowEnd(window);')
