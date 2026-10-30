"""Bounded multi-lobe material jobs; keep native sampling and fallback ordering."""
from .native_gpu_paths import once

def patch(out):
 p=out/'native_gpu_early.h';s=p.read_text()
 state=r"""
inline unsigned materialJobLobes=1;
inline std::atomic<uint64_t> jobCalls[2]{},jobMulti[2]{},jobLobes[2]{},jobPackets[2]{},jobLimited[2]{};
inline void materialJobReset(){
 const char* v=std::getenv("XPU2_MATERIAL_JOB_LOBES");
 materialJobLobes=v&&!std::strcmp(v,"2")?2:v&&!std::strcmp(v,"4")?4:1;
 for(unsigned i=0;i<2;++i)jobCalls[i]=jobMulti[i]=jobLobes[i]=jobPackets[i]=jobLimited[i]=0;
}
inline void materialJobFinish(){
 if(const char* path=std::getenv("XPU2_MATERIAL_JOB_PROFILE"))if(FILE* f=std::fopen(path,"a")){
  for(unsigned i=0;i<2;++i)std::fprintf(f,"{\"phase\":%u,\"limit\":%u,\"calls\":%llu,\"multi_lobe_jobs\":%llu,\"lobes\":%llu,\"packets\":%llu,\"limited\":%llu}\n",i,materialJobLobes,(unsigned long long)jobCalls[i].load(),(unsigned long long)jobMulti[i].load(),(unsigned long long)jobLobes[i].load(),(unsigned long long)jobPackets[i].load(),(unsigned long long)jobLimited[i].load());
  std::fclose(f);
 }
}
"""
 s=once(s,'inline int materialAdmissionMode=0;',state+'\ninline int materialAdmissionMode=0;')
 s=once(s,'inline void admissionReset(){','inline void admissionReset(){materialJobReset();')
 s=once(s,'inline void admissionFinish(){','inline void admissionFinish(){materialJobFinish();')
 s+=r"""
extern "C" unsigned CPP_gpuMaterialJobLimit(){return xpu2::nativepath::materialJobLobes;}
extern "C" void CPP_gpuMaterialJobCount(unsigned lobes,unsigned packets,unsigned limited){
 using namespace xpu2::nativepath;
 if(materialJobLobes>1 && (lobes>materialJobLobes || packets>32))throw std::logic_error("Material job exceeded bound");
 unsigned i=recordingWindow()?0:1;
 ++jobCalls[i];jobMulti[i]+=lobes>1;jobLobes[i]+=lobes;jobPackets[i]+=packets;jobLimited[i]+=limited;
}
"""
 p.write_text(s)
 p=out/'PathIntegratorUtil.ispc';s=p.read_text()
 anchor='extern "C" uniform bool CPP_gpuCpuAheadEnabled();'
 s=s.replace(anchor,'extern "C" uniform unsigned CPP_gpuMaterialJobLimit();\nextern "C" void CPP_gpuMaterialJobCount(uniform unsigned lobes,uniform unsigned packets,uniform unsigned limited);\n'+anchor,1)
 s=once(s,'    uniform bool haveGpu=false;','    uniform bool haveGpu=false;\n    uniform unsigned jobLimit=CPP_gpuMaterialJobLimit(),jobLobes=0,jobPackets=0,jobLimited=0;')
 s=once(s,'        if(CPP_gpuCpuAheadEnabled() && haveGpu)continue;\n        int count=BsdfSampler_getLobeSampleCount(&bSampler,k);',r"""        if(jobLimit==1 && CPP_gpuCpuAheadEnabled() && haveGpu)continue;
        int count=BsdfSampler_getLobeSampleCount(&bSampler,k);
        uniform int packetCount=reduce_max(count);
        // Keep the existing 32-packet native window bound. Rejected work stays native.
        if(jobLimit>1 && (jobLobes>=jobLimit || packetCount<1 || packetCount>16 || jobPackets+packetCount>32)){
            ++jobLimited;continue;
        }""")
 s=once(s,'        haveGpu=haveGpu || prepared[k];','        if(prepared[k]){++jobLobes;jobPackets+=packetCount;}\n        haveGpu=haveGpu || prepared[k];')
 s=once(s,'    if(anyPrepared)CPP_gpuMaterialStageBegin(tokens,BSDF_MAX_LOBE*16);','    CPP_gpuMaterialJobCount(jobLobes,jobPackets,jobLimited);\n    if(anyPrepared)CPP_gpuMaterialStageBegin(tokens,BSDF_MAX_LOBE*16);')
 p.write_text(s)
