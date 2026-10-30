"""Measure integration phases and test exact lane-parallel packet packing."""
from pathlib import Path
import re
from . import native_wide_window as base
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
DECL = '''
extern "C" uniform uint64 CPP_gpuIntegrationBegin();
extern "C" void CPP_gpuIntegrationEnd(uniform unsigned int phase,uniform uint64 start);
extern "C" uniform unsigned int CPP_gpuIntegrationSubmitPhase();
extern "C" uniform int CPP_gpuVectorPackingMode();
extern "C" void CPP_gpuPackingCount(uniform unsigned int count);
extern "C" void CPP_gpuVerifyPacking(const uniform float *uniform input,const uniform uint32 *uniform pixels,const uniform float *uniform expected,const uniform uint32 *uniform expectedPixels);
'''
def header(text):
    text=base.header(text)
    text=once(text,'inline void windowReset(){','inline void windowReset(){integrationReset();')
    text=once(text,'inline void windowFinish(){','inline void windowFinish(){integrationFinish();')
    text=once(text,'extern "C" void CPP_gpuEarlyCollect(moonray::pbr::TLState* tls,uint64_t token,float* result){','extern "C" void CPP_gpuEarlyCollect(moonray::pbr::TLState* tls,uint64_t token,float* result){\n    xpu2::nativepath::IntegrationTimer timer(5);')
    text=once(text,'extern "C" void CPP_gpuWindowPublish(uint64_t handle){','extern "C" void CPP_gpuWindowPublish(uint64_t handle){\n    xpu2::nativepath::IntegrationTimer timer(6);')
    text=once(text,'extern "C" void CPP_gpuEarlySubmitGroup(const float* input,const uint32_t* pixels,unsigned count,uint64_t* tokens){','extern "C" void CPP_gpuEarlySubmitGroup(const float* input,const uint32_t* pixels,unsigned count,uint64_t* tokens){\n    xpu2::nativepath::IntegrationTimer timer(xpu2::nativepath::recordingWindow()?7:xpu2::nativepath::currentWindow && xpu2::nativepath::currentWindow->replay?8:9);')
    return (HERE/'native_integration_profile.inc').read_text(encoding='utf-8-sig')+'\n'+text+'\nextern "C" unsigned CPP_gpuIntegrationSubmitPhase(){return xpu2::nativepath::recordingWindow()?1:2;}\n'

def timed_function(text,signature,phase):
    start=text.index(signature);brace=text.index('{',start);depth=1;end=brace+1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    body=text[brace+1:end-1]
    if re.search(r'\breturn\b',re.sub(r'//[^\n]*|/\*.*?\*/','',body,flags=re.S)):raise ValueError('Unexpected early timer return')
    return text[:brace+1]+'\n    uniform uint64 phaseStart=CPP_gpuIntegrationBegin();\n'+body+f'\n    CPP_gpuIntegrationEnd({phase},phaseStart);\n'+text[end-1:]

def ispc(text,bsdf_header):
    text=base.ispc(text,bsdf_header)
    start=text.index('inline uniform bool xpu2PrepareLobe(')
    end=text.index('    return xpu2Prepared;',start)
    part=text[start:end]
    first=part.index('                    foreach_active(lane){')
    last=part.index('\n                    }',first)+len('\n                    }')
    original=part[first:last]
    assignments=original[original.index('                        xpu2Pixels'):original.rindex('\n                    }')]
    parallel=assignments.replace('xpu2Pixels[lane]=extract(sp.mPixel,lane);','xpu2Pixels[programIndex]=sp.mPixel;').replace('uniform int b=lane*24;','varying int b=programIndex*24;')
    parallel=re.sub(r'extract\(([^,]+),lane\)',r'\1',parallel).replace('(uniform int)', '(varying int)')
    replacement='''                    if(xpu2PackMode){
'''+parallel+'''
                        if(xpu2PackMode==2){
                            uniform float expected[192];uniform uint32 expectedPixels[8];
                            for(uniform int k=0;k<192;++k)expected[k]=0.f;
                            for(uniform int k=0;k<8;++k)expectedPixels[k]=0xffffffff;
                            {
                                uniform float *uniform xpu2Input=expected;
                                uniform uint32 *uniform xpu2Pixels=expectedPixels;
'''+original+'''
                            }
                            CPP_gpuVerifyPacking(xpu2Input,xpu2Pixels,expected,expectedPixels);
                        }
                    }else{
'''+original+'''
                    }'''
    part=once(part,original,replacement)
    part=once(part,'            uniform bool xpu2Grouped=CPP_gpuEarlyGrouped();','            uniform bool xpu2Grouped=CPP_gpuEarlyGrouped();\n            uniform int xpu2PackMode=CPP_gpuVectorPackingMode();\n            CPP_gpuPackingCount(reduce_max(lobeSampleCount));')
    text=text[:start]+DECL+part+text[end:]
    anchor='    if(!CPP_gpuMaterialStageMode(pbrTls) || !all(pv.nonMirrorDepth==0))return false;'
    text=once(text,anchor,anchor+'\n    uniform unsigned int phase=CPP_gpuIntegrationSubmitPhase();\n    uniform uint64 phaseStart=CPP_gpuIntegrationBegin();')
    text=once(text,'    return anyPrepared;','    CPP_gpuIntegrationEnd(phase,phaseStart);\n    return anyPrepared;')
    text=timed_function(text,'void xpu2PrepareCpuLobes(uniform PbrTLState *uniform pbrTls,\n    const varying BsdfSampler &bSampler,const varying Subpixel &sp',3)
    return timed_function(text,'void\nxpu2ResumeMaterial(',4)

def bundled(text):
    text=base.bundled(text)
    text=once(text,'// Restrict speculation to full primary SIMD blocks',DECL+'\n// Restrict speculation to full primary SIMD blocks')
    anchor='Bsdf_getLobeCount(&bsdf)==0)return;\n    varying BsdfSlice slice;'
    text=once(text,anchor,'Bsdf_getLobeCount(&bsdf)==0)return;\n    uniform uint64 phaseStart=CPP_gpuIntegrationBegin();\n    varying BsdfSlice slice;')
    return once(text,'    Arena_setPtr(tls->mArena,bookmark);','    Arena_setPtr(tls->mArena,bookmark);\n    CPP_gpuIntegrationEnd(0,phaseStart);')
