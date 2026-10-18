"""Strict copied-source early dispatch hooks. No installed/native source edits."""
from pathlib import Path
from .native_gpu_paths import once,adapter as late_adapter,cpp as late_cpp
HERE=Path(__file__).resolve().parent

def queue(text):
    # An independent generated queue: accepted outputs require no precomputed oracle.
    text=text.replace('&& std::strcmp(mode,"sentinel")))return;', '&& std::strcmp(mode,"sentinel") && std::strcmp(mode,"execute") && std::strcmp(mode,"execute_sentinel")))return;')
    text=once(text,'        std::lock_guard<std::mutex> lock(mutex);\n        if(count<1', '        const bool raw=!std::strcmp(mode,"execute")||!std::strcmp(mode,"execute_sentinel");\n        std::lock_guard<std::mutex> lock(mutex);\n        if(count<1')
    text=once(text,'U native[8];std::memcpy(native,output+i*8,28);native[7]=U(output[i*8+7]);','U native[8]{};if(!raw){std::memcpy(native,output+i*8,28);native[7]=U(output[i*8+7]);}')
    text=once(text,'if(std::memcmp(native,gpu+1,32))','if(!raw && std::memcmp(native,gpu+1,32))')
    text=once(text,'                ++accepted;','''                bool finite=true;
                for(int k=1;k<8;++k)if((gpu[k]&0x7f800000u)==0x7f800000u)finite=false;
                if(!finite||gpu[8]>1){++invalid;continue;}
                ++accepted;''')
    text=once(text,'if(!std::strcmp(mode,"replace") || !std::strcmp(mode,"sentinel"))', 'if(raw || !std::strcmp(mode,"replace") || !std::strcmp(mode,"sentinel"))')
    text=once(text,'std::memcpy(output+i*8,gpu+1,28);++replaced;', 'std::memcpy(output+i*8,gpu+1,28);output[i*8+7]=float(gpu[8]);++replaced;')
    text=once(text,'if(!std::strcmp(mode,"sentinel"))for', 'if(!std::strcmp(mode,"sentinel")||!std::strcmp(mode,"execute_sentinel"))for')
    text=once(text,'    bool ready=false, attempted=false;', '    unsigned long long diffuseReflection=0,diffuseTransmission=0,roughDiffuse=0;\n    bool ready=false, attempted=false;')
    text=once(text,'                ++accepted;', '                ++accepted;uint32_t kind,reflection;std::memcpy(&kind,input+i*24+1,4);std::memcpy(&reflection,input+i*24+20,4);if(kind==2)++roughDiffuse;else if(reflection)++diffuseReflection;else ++diffuseTransmission;')
    return text

def adapter(text):
    text=late_adapter(text)
    text=once(text,'    shaderBegin();','    shaderBegin();earlyReset();')
    text=once(text,'    shaderFinish(epoch);','    earlyFinish();shaderFinish(epoch);')
    text=once(text,'bool gpuEnabled(){return enabled&&fixed;}','bool gpuEnabled(){return false;}')
    return once(text,'#include "native_gpu_shading.h"','#include "native_gpu_shading.h"\nnamespace xpu2::nativepath {void earlyReset();void earlyFinish();}')

def cpp(text):
    return once(late_cpp(text),'#include "native_gpu_paths.inc"','#include "native_gpu_paths.inc"\n#include "native_gpu_early.h"')

def ispc(text,bsdf_header):
    start=bsdf_header.index('inline varying bool\nBsdfSampler_sample(')
    end=bsdf_header.index('\n\n//----------------------------------------------------------------------------',start)
    helper=bsdf_header[start:end].replace('BsdfSampler_sample(', 'xpu2ApplyBsdfSample(',1)
    helper=once(helper,'varying float r1, varying float r2, varying BsdfSample &sample)', 'varying float r1, varying float r2, varying BsdfSample &sample, const uniform float *uniform result)')
    helper=once(helper,'    sample.f = BsdfLobe_sample(lobe, *bSampler->mSlice, r1, r2, sample.wi, sample.pdf);', '''    sample.wi=Vec3f_ctor(result[programIndex*8],result[programIndex*8+1],result[programIndex*8+2]);
    sample.f=Color_ctor(result[programIndex*8+3],result[programIndex*8+4],result[programIndex*8+5]);
    sample.pdf=result[programIndex*8+6];''')
    declarations='''#include <moonray/rendering/shading/ispc/bsdf/BsdfLambert.isph>
#include <moonray/rendering/shading/ispc/bsdf/BsdfOrenNayar.isph>
#include <moonray/rendering/shading/ispc/bsdf/npr/BsdfFlatDiffuse.isph>
extern "C" uniform bool CPP_gpuEarlyEnabled(uniform PbrTLState *uniform tls);
extern "C" uniform uint64 CPP_gpuEarlySubmit(const uniform float *uniform input);
extern "C" void CPP_gpuEarlyCollect(uniform PbrTLState *uniform tls, uniform uint64 token, uniform float *uniform result);
extern "C" void xpu2NativeCpuBegin();
extern "C" void CPP_gpuEarlyCpuEnd();
'''+helper+'\n'
    text=once(text,'void\ndrawBsdfSamples(',declarations+'\nvoid\ndrawBsdfSamples(')
    text=once(text,"        // Loop over each lobe's samples",(HERE/'native_gpu_early_pack.ispc.inc').read_text()+"\n        // Loop over each lobe's samples")
    text=once(text,'''            bool isValid = BsdfSampler_sample(pbrTls, &bSampler, lobeIndex,
                    bsdfSample[0], bsdfSample[1], bsmp[s]);''','''            uniform float xpu2Result[64];
            varying bool useGpu=false;
            if(xpu2Prepared){
                CPP_gpuEarlyCollect(pbrTls,xpu2Tokens[s-bSampler.mLobeToSampleIndex[lobeIndex]],xpu2Result);
                useGpu=(intbits(xpu2Result[programIndex*8+3])&0x7f800000)!=0x7f800000;
            }
            bool isValid;
            if(useGpu)isValid=xpu2ApplyBsdfSample(pbrTls,&bSampler,lobeIndex,bsdfSample[0],bsdfSample[1],bsmp[s],xpu2Result);
            else isValid=BsdfSampler_sample(pbrTls,&bSampler,lobeIndex,bsdfSample[0],bsdfSample[1],bsmp[s]);''')
    text=once(text,'            LightSetSampler_intersectAndEval(&lSampler, pbrTls, shadingTls, P, cullingNormal, bsmp[s].wi,','            if(xpu2Prepared)xpu2NativeCpuBegin();\n            LightSetSampler_intersectAndEval(&lSampler, pbrTls, shadingTls, P, cullingNormal, bsmp[s].wi,')
    text=once(text,'                bsmp[s].tDirect = smartClamp(bsmp[s].tDirect, clampingValue);\n            }','                bsmp[s].tDirect = smartClamp(bsmp[s].tDirect, clampingValue);\n            }\n            if(xpu2Prepared)CPP_gpuEarlyCpuEnd();')
    return text
