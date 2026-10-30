"""Capture a complete native diffuse direct-light unit without replacing its result."""
from .native_gpu_paths import once

CPP = r'''
#include <mutex>
namespace xpu2::lightunit {
struct Capture {
    std::mutex mutex; FILE* file=nullptr; uint64_t seen[2]={},written[2]={};
    Capture(){if(const char* path=std::getenv("XPU2_LIGHT_CAPTURE")){
        file=std::fopen(path,"wb");if(!file)throw std::runtime_error("Cannot open light-unit capture");
        if(std::fwrite("XDL1",1,4,file)!=4)throw std::runtime_error("Cannot write light-unit header");
    }}
    ~Capture(){if(file){std::fclose(file);if(const char* path=std::getenv("XPU2_LIGHT_CAPTURE")){
        std::string name=std::string(path)+".json";if(FILE* report=std::fopen(name.c_str(),"w")){
            std::fprintf(report,"{\"seen\":[%llu,%llu],\"written\":[%llu,%llu],\"limit_per_kind\":65536}\n",(unsigned long long)seen[0],(unsigned long long)seen[1],(unsigned long long)written[0],(unsigned long long)written[1]);std::fclose(report);
        }
    }}}
};
inline Capture& capture(){static Capture state;return state;}
}
extern "C" bool CPP_xpu2LightCaptureEnabled(){return xpu2::lightunit::capture().file!=nullptr;}
extern "C" void CPP_xpu2LightCapture(const float* inputs,const float* expected,unsigned count){
    auto& state=xpu2::lightunit::capture();std::lock_guard<std::mutex> lock(state.mutex);
    if(!state.file || count>8)throw std::logic_error("Invalid light-unit capture");
    for(unsigned lane=0;lane<count;++lane){
        const float* input=inputs+lane*32;uint32_t kind;std::memcpy(&kind,input,4);
        if(kind<1||kind>2)throw std::logic_error("Invalid light-unit kind");
        ++state.seen[kind-1];if(state.written[kind-1]>=65536)continue;
        if(std::fwrite(input,4,32,state.file)!=32 || std::fwrite(expected+lane*8,4,8,state.file)!=8)throw std::runtime_error("Light-unit capture write failed");
        ++state.written[kind-1];
    }
}
'''

ISPC = r'''
extern "C" uniform bool CPP_xpu2LightCaptureEnabled();
extern "C" void CPP_xpu2LightCapture(const uniform float *uniform input,const uniform float *uniform expected,uniform unsigned int count);
inline void xpu2CaptureLightUnit(const varying BsdfLobe *uniform lobe,
    const varying BsdfSlice &slice,const varying LightSample &lsmp,const varying Color &throughput,
    float ni,int nk,const varying Color &f,float pdf,const varying Color &t){
    if(lobe->mName!=BSDF_LOBE_LAMBERT && lobe->mName!=BSDF_LOBE_FLAT_DIFFUSE)return;
    uniform bool rough=lobe->mName==BSDF_LOBE_FLAT_DIFFUSE;
    const varying LambertBsdfLobe *uniform lambert=(const varying LambertBsdfLobe *uniform)lobe;
    const varying FlatDiffuseBsdfLobe *uniform flat=(const varying FlatDiffuseBsdfLobe *uniform)lobe;
    const varying OrenNayarBsdfLobe *uniform oren=(const varying OrenNayarBsdfLobe *uniform)lobe;
    bool eligible=!isActive(BsdfLobe_getFresnel(lobe)) && !BsdfLobe_getIsSpherical(lobe) && slice.mShadowTerminatorFix==0;
    if(rough)eligible &= flat->mFlatness==0.f && flat->mTerminatorShift==0.f && flat->mFlatnessFalloff>=0.f && flat->mFlatnessFalloff<=1.f;
    if(eligible){
        const Vec3f N=rough?getN(oren->mFrame):getN(lambert->mFrame);
        const Color albedo=rough?oren->mAlbedo:lambert->mAlbedo;
        float weight=powerHeuristic(ni*lsmp.misPdf,nk*pdf);
        uniform float input[8*32],expected[8*8];uniform unsigned int count=0;
        foreach_active(lane){
            uniform int b=count*32,o=count*8;
            for(uniform int j=0;j<32;++j)input[b+j]=0.f;
            input[b]=floatbits((uniform int)(rough?2:1));
            input[b+1]=extract(N.x,lane);input[b+2]=extract(N.y,lane);input[b+3]=extract(N.z,lane);
            input[b+4]=extract(lsmp.wi.x,lane);input[b+5]=extract(lsmp.wi.y,lane);input[b+6]=extract(lsmp.wi.z,lane);
            input[b+7]=extract(slice.mWo.x,lane);input[b+8]=extract(slice.mWo.y,lane);input[b+9]=extract(slice.mWo.z,lane);
            input[b+10]=extract(albedo.r,lane);input[b+11]=extract(albedo.g,lane);input[b+12]=extract(albedo.b,lane);
            input[b+13]=extract(lambert->mScale.r,lane);input[b+14]=extract(lambert->mScale.g,lane);input[b+15]=extract(lambert->mScale.b,lane);
            input[b+16]=extract(throughput.r,lane);input[b+17]=extract(throughput.g,lane);input[b+18]=extract(throughput.b,lane);
            input[b+19]=extract(lsmp.Li.r,lane);input[b+20]=extract(lsmp.Li.g,lane);input[b+21]=extract(lsmp.Li.b,lane);
            input[b+22]=extract(ni,lane);input[b+23]=(uniform float)extract(nk,lane);
            input[b+24]=extract(lsmp.pdf,lane);input[b+25]=extract(lsmp.misPdf,lane);
            input[b+26]=rough?extract(oren->mA,lane):0.f;input[b+27]=rough?extract(oren->mB,lane):0.f;
            input[b+28]=extract(slice.mIncludeCosineTerm,lane)?1.f:0.f;
            expected[o]=extract(f.r,lane);expected[o+1]=extract(f.g,lane);expected[o+2]=extract(f.b,lane);expected[o+3]=extract(pdf,lane);
            expected[o+4]=extract(t.r,lane);expected[o+5]=extract(t.g,lane);expected[o+6]=extract(t.b,lane);expected[o+7]=extract(weight,lane);
            ++count;
        }
        CPP_xpu2LightCapture(input,expected,count);
    }
}
'''

def patch(out):
    p=out/'native_gpu_early.h';p.write_text(p.read_text()+CPP)
    p=out/'PathIntegratorUtil.ispc';s=p.read_text()
    s=once(s,'inline void\nintegrateLightSetSample(',ISPC+'\ninline void\nintegrateLightSetSample(')
    s=once(s,'        Color t = factor * f * powerHeuristic(ni * lsmp.misPdf, nk * pdf);','        Color t = factor * f * powerHeuristic(ni * lsmp.misPdf, nk * pdf);\n        if(CPP_xpu2LightCaptureEnabled())xpu2CaptureLightUnit(lobe,*slice,lsmp,pv.pathThroughput,ni,nk,f,pdf,t);')
    p.write_text(s)
