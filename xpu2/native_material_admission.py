"""Gate speculative material work before native setup and GPU packet preparation."""
from .native_gpu_paths import once


def patch(out):
 p=out/'native_gpu_early.h';s=p.read_text()
 anchor='struct WindowPacket {'
 state=r'''inline int materialAdmissionMode=0;
inline bool admissionProfile=false;
inline std::atomic<uint64_t> admissionCalls[3]{},admissionRejected[3]{},admissionPacks[3]{};
inline void admissionReset(){
    const char* m=std::getenv("XPU2_MATERIAL_ADMISSION");
    materialAdmissionMode=m&&!std::strcmp(m,"supported")?1:m&&!std::strcmp(m,"cost")?2:m&&!std::strcmp(m,"cpu")?3:0;
    admissionProfile=std::getenv("XPU2_ADMISSION_PROFILE")!=nullptr;
    for(unsigned i=0;i<3;++i)admissionCalls[i]=admissionRejected[i]=admissionPacks[i]=0;
}
inline void admissionFinish(){
    if(const char* p=std::getenv("XPU2_ADMISSION_PROFILE"))if(FILE* f=std::fopen(p,"a")){
        std::fprintf(f,"{\"mode\":%d,\"window_calls\":%llu,\"window_rejected\":%llu,\"submit_calls\":%llu,\"submit_rejected\":%llu,\"lobe_calls\":%llu,\"lobe_rejected\":%llu,\"record_packets\":%llu,\"replay_packets\":%llu,\"direct_packets\":%llu,\"record_bytes\":%llu,\"replay_bytes\":%llu,\"direct_bytes\":%llu}\n",materialAdmissionMode,
        (unsigned long long)admissionCalls[0].load(),(unsigned long long)admissionRejected[0].load(),(unsigned long long)admissionCalls[1].load(),(unsigned long long)admissionRejected[1].load(),(unsigned long long)admissionCalls[2].load(),(unsigned long long)admissionRejected[2].load(),
        (unsigned long long)admissionPacks[0].load(),(unsigned long long)admissionPacks[1].load(),(unsigned long long)admissionPacks[2].load(),(unsigned long long)(admissionPacks[0].load()*800),(unsigned long long)(admissionPacks[1].load()*800),(unsigned long long)(admissionPacks[2].load()*800));std::fclose(f);
    }
}
'''
 s=once(s,anchor,state+anchor)
 s=once(s,'WindowScope(){for(auto& b:blocks)b.packets.reserve(32);}', 'WindowScope(){if(!materialAdmissionMode)for(auto& b:blocks)b.packets.reserve(32);}')
 s=once(s,'inline void windowReset(){','inline void windowReset(){admissionReset();')
 s=once(s,'inline void windowFinish(){','inline void windowFinish(){admissionFinish();')
 s=once(s,'        b.packets.emplace_back();auto& p=b.packets.back();','        if(materialAdmissionMode && b.packets.empty())b.packets.reserve(32);\n        b.packets.emplace_back();auto& p=b.packets.back();')
 s+=r'''
extern "C" int CPP_gpuMaterialAdmissionMode(){return xpu2::nativepath::materialAdmissionMode;}
extern "C" void CPP_gpuAdmissionCount(unsigned stage,bool admitted){
    using namespace xpu2::nativepath;
    if(stage>2)throw std::logic_error("Invalid admission stage");
    // Existing admission restricts native shading to one render worker.
    if(admissionProfile){++admissionCalls[stage];if(!admitted)++admissionRejected[stage];}
}
extern "C" void CPP_gpuAdmissionPacking(unsigned packets){
    using namespace xpu2::nativepath;
    if(admissionProfile)admissionPacks[recordingWindow()?0:currentWindow&&currentWindow->replay?1:2]+=packets;
}
'''
 p.write_text(s)
 p=out/'PathIntegratorUtil.ispc';s=p.read_text()
 s=once(s,'extern "C" uniform bool CPP_gpuEarlyEnabled', '#include "native_material_admission.isph"\nextern "C" uniform bool CPP_gpuEarlyEnabled')
 anchor='        uniform bool xpu2Prepared=false;'
 s=once(s,anchor,anchor+'''
        uniform int admissionMode=CPP_gpuMaterialAdmissionMode();
        uniform bool lobeAdmitted=xpu2AdmissionLobe(lobe,lobeSampleCount,admissionMode);
        CPP_gpuAdmissionCount(2,lobeAdmitted);
        if(!lobeAdmitted)return false;
''')
 s=once(s,'            CPP_gpuPackingCount(reduce_max(lobeSampleCount));','            CPP_gpuPackingCount(reduce_max(lobeSampleCount));\n            CPP_gpuAdmissionPacking(reduce_max(lobeSampleCount));')
 anchor='    uniform bool admitted=all(pv.nonMirrorDepth==0) && CPP_gpuMaterialStageMode(pbrTls)!=0;'
 s=once(s,anchor,anchor+'''
    if(admitted){
        uniform int admissionMode=CPP_gpuMaterialAdmissionMode();
        uniform bool useful=admissionMode==0;
        if(admissionMode)for(uniform int k=0;k<BsdfSampler_getLobeCount(&bSampler);++k){
            const varying BsdfLobe *uniform lobe=BsdfSampler_getLobe(&bSampler,k);
            if(isActive(lobe) && xpu2AdmissionLobe(lobe,BsdfSampler_getLobeSampleCount(&bSampler,k),admissionMode))useful=true;
        }
        CPP_gpuAdmissionCount(1,useful);
        if(!useful)return false;
    }
''')
 p.write_text(s)
 p=out/'PathIntegratorBundled.ispc';s=p.read_text()
 s=once(s,'#include "BsdfSampler.isph"','#include "BsdfSampler.isph"\n#include "native_material_admission.isph"')
 anchor='    uniform uint64 phaseStart=CPP_gpuIntegrationBegin();'
 s=once(s,anchor,'''    uniform bool useful=xpu2AdmissionBsdf(bsdf,CPP_gpuMaterialAdmissionMode());
    CPP_gpuAdmissionCount(0,useful);
    if(!useful)return;
'''+anchor)
 p.write_text(s)
