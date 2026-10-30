"""Reuse sample coordinates already owned by the current material continuation."""
from .native_gpu_paths import once

def patch(out):
 p=out/'native_gpu_early.h';s=p.read_text()
 s=once(s,'inline void windowReset(){',r'''inline int sampleReuseMode=0;
inline std::atomic<uint64_t> sampleReuseCpu{0},sampleReuseGpu{0},sampleReuseChecked{0},sampleReuseMismatch{0};
inline void windowReset(){
    const char* mode=std::getenv("XPU2_SAMPLE_REUSE");sampleReuseMode=mode && !std::strcmp(mode,"verify")?2:mode && !std::strcmp(mode,"1")?1:0;
    sampleReuseCpu=0;sampleReuseGpu=0;sampleReuseChecked=0;sampleReuseMismatch=0;''')
 s=once(s,'inline void windowFinish(){',r'''inline void windowFinish(){
    if(sampleReuseMismatch)throw std::logic_error("Cached sample coordinates differ");
    if(const char* name=std::getenv("XPU2_SAMPLE_REUSE_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        std::fprintf(f,"{\"mode\":%d,\"cpu_lanes\":%llu,\"gpu_lanes\":%llu,\"checked\":%llu,\"mismatch\":%llu}\n",sampleReuseMode,(unsigned long long)sampleReuseCpu.load(),(unsigned long long)sampleReuseGpu.load(),(unsigned long long)sampleReuseChecked.load(),(unsigned long long)sampleReuseMismatch.load());std::fclose(f);
    }''')
 s+=r'''
extern "C" int CPP_gpuSampleReuseMode(){return xpu2::nativepath::sampleReuseMode;}
extern "C" void CPP_gpuSampleReuseCount(unsigned cpu,unsigned gpu,unsigned checked,unsigned mismatch){
    using namespace xpu2::nativepath;
    sampleReuseCpu+=cpu;sampleReuseGpu+=gpu;sampleReuseChecked+=checked;sampleReuseMismatch+=mismatch;
    if(mismatch)throw std::logic_error("Cached native sample mismatch");
}
extern "C" void CPP_gpuEarlyCollectSamples(moonray::pbr::TLState* tls,uint64_t token,float* result,float* samples){
    using namespace xpu2::nativepath;
    std::fill(samples,samples+16,std::numeric_limits<float>::quiet_NaN());
    if(token){
        // Immutable numeric input belongs to this ticket until Collect releases it.
        // Reuse is allowed only for lanes accepted by the original collector.
        const auto& ticket=*reinterpret_cast<Queue::Ticket*>(token);
        if(ticket->revision!=epoch)throw std::logic_error("Cached sample epoch mismatch");
        for(unsigned lane=0;lane<8;++lane){samples[lane*2]=ticket->input[lane*24+11];samples[lane*2+1]=ticket->input[lane*24+12];}
    }
    CPP_gpuEarlyCollect(tls,token,result);
}
'''
 p.write_text(s)
 p=out/'PathIntegratorUtil.ispc';s=p.read_text();start=s.index('void\nxpu2ResumeMaterial(');end=s.index('void\ndrawBsdfSamples(',start);body=s[start:end]
 body=once(body,'    uniform uint64 phaseStart=CPP_gpuIntegrationBegin();','''    uniform uint64 phaseStart=CPP_gpuIntegrationBegin();
    uniform int sampleReuseMode=CPP_gpuSampleReuseMode();
    uniform unsigned reusedCpu=0,reusedGpu=0,checkedSamples=0,badSamples=0;''')
 body=once(body,'            getSample(bsdfSamples, bsdfSample, pv.nonMirrorDepth, *pbrTls->mFs);','            if(!sampleReuseMode)getSample(bsdfSamples, bsdfSample, pv.nonMirrorDepth, *pbrTls->mFs);')
 body=once(body,'            uniform float xpu2Result[64];','            uniform float xpu2Result[64];\n            uniform float cachedCoordinates[16];')
 line='                CPP_gpuEarlyCollect(pbrTls,xpu2Tokens[s-bSampler.mLobeToSampleIndex[lobeIndex]],xpu2Result);'
 body=once(body,line,'''                if(sampleReuseMode)CPP_gpuEarlyCollectSamples(pbrTls,xpu2Tokens[s-bSampler.mLobeToSampleIndex[lobeIndex]],xpu2Result,cachedCoordinates);
                else CPP_gpuEarlyCollect(pbrTls,xpu2Tokens[s-bSampler.mLobeToSampleIndex[lobeIndex]],xpu2Result);''')
 body=once(body,'            if(cpuPrepared[lobeIndex])CPP_gpuCpuAheadCount(1,true);', '''            if(sampleReuseMode){
                bool cached=cpuPrepared[lobeIndex] || useGpu;
                float r1=0.f,r2=0.f;
                if(cpuPrepared[lobeIndex]){r1=bsmp[s].sample.x;r2=bsmp[s].sample.y;}
                else if(useGpu){r1=cachedCoordinates[programIndex*2];r2=cachedCoordinates[programIndex*2+1];}
                reusedCpu+=getActiveLaneCount(cached && cpuPrepared[lobeIndex]);
                reusedGpu+=getActiveLaneCount(cached && !cpuPrepared[lobeIndex]);
                if(sampleReuseMode==2){
                    getSample(bsdfSamples,bsdfSample,pv.nonMirrorDepth,*pbrTls->mFs);
                    checkedSamples+=getActiveLaneCount(cached);
                    badSamples+=getActiveLaneCount(cached && (intbits(r1)!=intbits(bsdfSample[0]) || intbits(r2)!=intbits(bsdfSample[1])));
                }else if(cached){
                    bsdfSample[0]=r1;bsdfSample[1]=r2;
                    // getSample's only sampler mutation is one index advance.
                    ++bsdfSamples.mSampleNumber;
                }else getSample(bsdfSamples,bsdfSample,pv.nonMirrorDepth,*pbrTls->mFs);
            }
            if(cpuPrepared[lobeIndex])CPP_gpuCpuAheadCount(1,true);''')
 body=once(body,'    CPP_gpuIntegrationEnd(4,phaseStart);','''    if(sampleReuseMode)CPP_gpuSampleReuseCount(reusedCpu,reusedGpu,checkedSamples,badSamples);
    CPP_gpuIntegrationEnd(4,phaseStart);''')
 decl='''extern "C" uniform int CPP_gpuSampleReuseMode();
extern "C" void CPP_gpuSampleReuseCount(uniform unsigned int cpu,uniform unsigned int gpu,uniform unsigned int checked,uniform unsigned int mismatch);
extern "C" void CPP_gpuEarlyCollectSamples(uniform PbrTLState *uniform tls,uniform uint64 token,uniform float *uniform result,uniform float *uniform samples);
'''
 p.write_text(s[:start]+decl+body+s[end:])
