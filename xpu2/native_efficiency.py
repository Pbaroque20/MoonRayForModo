"""Opt-in native transport efficiency and same-invocation CPU lobe lookahead."""
from pathlib import Path
from . import native_transport as base
from .native_gpu_paths import once
HERE=Path(__file__).resolve().parent
adapter=base.adapter
cpp=base.cpp
cuda=base.cuda
shadow_header=base.shadow_header
driver=base.driver

def queue(text):
    text=base.queue(text)
    text=once(text,'bool flightsReady=false,flightBroken=false;',"""bool flightsReady=false,flightBroken=false;
    bool leanWire=std::getenv("XPU2_LEAN_WIRE") && !std::strcmp(std::getenv("XPU2_LEAN_WIRE"),"1");
    unsigned long long staticUploadBytes=0,avoidedEchoBytes=0,pollSkipped=0;
    unsigned pollUs=std::getenv("XPU2_POLL_US")?unsigned(std::max(0,std::min(100,std::atoi(std::getenv("XPU2_POLL_US"))))):0;
    std::chrono::steady_clock::time_point nextPoll[4]{};""")
    text=once(text,'        for(unsigned k=0;k<512;++k)s.lengths()[k]=96;',"""        for(unsigned k=0;k<512;++k)s.lengths()[k]=96;
        if(leanWire){check(fn_cuMemcpyHtoDAsync_v2(s.device[1],s.lengths(),512*4,s.stream));staticUploadBytes+=512*4;}""")
    text=once(text,'            check(fn_cuMemcpyHtoDAsync_v2(s.device[1],s.lengths(),count*4,s.stream));','            if(!leanWire)check(fn_cuMemcpyHtoDAsync_v2(s.device[1],s.lengths(),count*4,s.stream));')
    text=once(text,'regularUploadBytes+=count*100;lastTransferBytes=count*232;','regularUploadBytes+=count*(leanWire?96:100);lastTransferBytes=count*(leanWire?132:232);')
    text=once(text,'lastTransferBytes=compactBytes+count*132;','lastTransferBytes=compactBytes+count*(leanWire?36:132);')
    text=once(text,'        check(fn_cuMemcpyDtoHAsync_v2(s.returned(),s.device[2],count*96,s.stream));',"""        if(!leanWire)check(fn_cuMemcpyDtoHAsync_v2(s.returned(),s.device[2],count*96,s.stream));
        else avoidedEchoBytes+=count*96;""")
    # Only the flight validation changes; the synchronous diagnostic remains intact.
    start=text.index('void finishFlight(');end=text.index('    void summary()',start)
    part=text[start:end].replace('if(std::memcmp(returned+i*24,input+i*24,96))','if(!leanWire && std::memcmp(returned+i*24,input+i*24,96))')
    text=text[:start]+part+text[end:]
    text=once(text,'        if(!ready){++errors;return false;}', '        if(!ready){++errors;return false;}\n        if(leanWire && std::strcmp(mode,"execute") && std::strcmp(mode,"execute_sentinel"))throw std::logic_error("Lean wire requires native execute mode");')
    text=once(text,'        s.busy=true;++flightSubmitted;return true;','        nextPoll[index]=std::chrono::steady_clock::now()+std::chrono::microseconds(pollUs);\n        s.busy=true;++flightSubmitted;return true;')
    text=once(text,'    if(flightBroken)return -1;',"""    if(flightBroken)return -1;
    if(pollUs && std::chrono::steady_clock::now()<nextPoll[index]){++pollSkipped;return 0;}
    nextPoll[index]=std::chrono::steady_clock::now()+std::chrono::microseconds(pollUs);""")
    return text

def profile(text):
    text=base.profile(text)
    return once(text,'    shaderQueue.reset();',r"""    if(const char* name=std::getenv("XPU2_EFFICIENCY_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        std::fprintf(f,"{\"lean_wire\":%s,\"poll_us\":%u,\"poll_skipped\":%llu,\"static_upload_bytes\":%llu,\"avoided_echo_bytes\":%llu}\n",d.leanWire?"true":"false",d.pollUs,d.pollSkipped,d.staticUploadBytes,d.avoidedEchoBytes);std::fclose(f);
    }
    shaderQueue.reset();""")

DECL=r"""
extern "C" uniform bool CPP_gpuCpuAheadEnabled();
extern "C" void CPP_gpuCpuAheadCount(uniform unsigned int packets,uniform bool consumed);
void xpu2PrepareCpuLobes(uniform PbrTLState *uniform pbrTls,
    const varying BsdfSampler &bSampler,const varying Subpixel &sp,const varying PathVertex &pv,
    varying uint32_t sequenceID,varying BsdfSample *uniform bsmp,
    const uniform bool *uniform gpuPrepared,uniform bool *uniform cpuPrepared,varying bool *uniform cpuValid);
"""
EXTRA=',uniform bool *uniform cpuPrepared,varying bool *uniform cpuValid'

def header(text):
    text=base.header(text)
    text=once(text,'inline void stageReset(){',r"""inline std::atomic<uint64_t> cpuAheadPacked{0},cpuAheadUsed{0};
inline void stageReset(){cpuAheadPacked=0;cpuAheadUsed=0;""")
    text=once(text,'inline void stageFinish(){',r"""inline void stageFinish(){
    if(cpuAheadPacked!=cpuAheadUsed)throw std::logic_error("Unconsumed CPU shading work");
    if(const char* name=std::getenv("XPU2_CPU_AHEAD_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        std::fprintf(f,"{\"packed\":%llu,\"consumed\":%llu}\n",(unsigned long long)cpuAheadPacked.load(),(unsigned long long)cpuAheadUsed.load());std::fclose(f);
    }
""")
    return text+r"""
extern "C" bool CPP_gpuCpuAheadEnabled(){return std::getenv("XPU2_CPU_LOBE_AHEAD") && !std::strcmp(std::getenv("XPU2_CPU_LOBE_AHEAD"),"1");}
extern "C" void CPP_gpuCpuAheadCount(unsigned packets,bool consumed){using namespace xpu2::nativepath;if(consumed)cpuAheadUsed+=packets;else cpuAheadPacked+=packets;}
"""

def ispc(text,bsdf_header):
    text=base.ispc(text,bsdf_header)
    # Opt-in deterministic whole-lobe ownership: retain the first GPU lobe,
    # compute later lobes on this native worker while that lobe is in flight.
    start=text.index('uniform bool xpu2SubmitMaterial(',text.index('uniform bool xpu2SubmitMaterial(')+1)
    end=text.index('void\nxpu2ResumeMaterial(',start)
    part=text[start:end]
    part=once(part,'    varying int seed=0;','    varying int seed=0;\n    uniform bool haveGpu=false;')
    part=once(part,'        int count=BsdfSampler_getLobeSampleCount(&bSampler,k);','        if(CPP_gpuCpuAheadEnabled() && haveGpu)continue;\n        int count=BsdfSampler_getLobeSampleCount(&bSampler,k);')
    key='prepared[k]=xpu2PrepareLobe(pbrTls,bSampler,sp,pv,lobe,count,sampler,&tokens[k*16]);'
    part=once(part,key,key+'\n        haveGpu=haveGpu || prepared[k];')
    text=text[:start]+'extern "C" uniform bool CPP_gpuCpuAheadEnabled();\n'+part+text[end:]
    # Extend only resume declaration/definition, not the submission signature.
    key='    uniform uint64 *uniform tokens,uniform bool *uniform prepared);'
    pos=text.index('void xpu2ResumeMaterial(');at=text.index(key,pos)
    text=text[:at]+text[at:].replace(key,key[:-2]+EXTRA+');',1)
    text=once(text,'uniform bool *uniform xpu2AheadPrepared)','uniform bool *uniform xpu2AheadPrepared'+EXTRA+')')
    pos=text.index('void\nxpu2ResumeMaterial(');end=text.index('void\ndrawBsdfSamples(',pos)
    part=text[pos:end]
    part=once(part,'        if(!xpu2Prepared)xpu2Prepared=', '        if(!xpu2Prepared && !cpuPrepared[lobeIndex])xpu2Prepared=')
    part=once(part,'            if(useGpu)isValid=', '            if(cpuPrepared[lobeIndex])isValid=cpuValid[s];\n            else if(useGpu)isValid=')
    # Count once per sample packet, outside varying validity branches.
    part=once(part,'            bool isValid;','            if(cpuPrepared[lobeIndex])CPP_gpuCpuAheadCount(1,true);\n            bool isValid;')
    text=text[:pos]+DECL+(HERE/'native_cpu_ahead.ispc.inc').read_text()+'\n'+part+text[end:]
    return text

def multisampler(text):
    text=base.multisampler(text)
    key='    uniform uint64 *uniform tokens,uniform bool *uniform prepared);'
    pos=text.index('void xpu2ResumeMaterial(');at=text.index(key,pos)
    text=text[:at]+text[at:].replace(key,key[:-2]+EXTRA+');'+DECL,1)
    anchor='    uniform bool xpu2LightFirst=xpu2Staged && CPP_gpuMaterialStageMode(pbrTls)==2;'
    text=once(text,anchor,anchor+'\n    uniform bool cpuPrepared[BSDF_MAX_LOBE];\n    for(uniform int k=0;k<BSDF_MAX_LOBE;++k)cpuPrepared[k]=false;\n    varying bool *uniform cpuValid=NULL;')
    anchor='    if(!xpu2LightFirst){'
    text=once(text,anchor,"""    if(xpu2Staged && CPP_gpuCpuAheadEnabled()){
        cpuValid=(varying bool *uniform)Arena_allocArray(arena,bsdfSampleCount,sizeof(varying bool));
        xpu2PrepareCpuLobes(pbrTls,bSampler,sp,pv,sequenceID,bsmp,xpu2Prepared,cpuPrepared,cpuValid);
    }
"""+anchor)
    old='parentLobeLightSets,xpu2Tokens,xpu2Prepared);'
    if text.count(old)!=2:raise ValueError('Resume call drift')
    return text.replace(old,'parentLobeLightSets,xpu2Tokens,xpu2Prepared,cpuPrepared,cpuValid);')
