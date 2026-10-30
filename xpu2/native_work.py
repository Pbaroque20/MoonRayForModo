"""Bounded lobe lookahead and shared-input CUDA uploads, copied native source only."""
from pathlib import Path
from . import native_batch as batch
from .native_gpu_paths import once
HERE=Path(__file__).resolve().parent
adapter=batch.adapter
cpp=batch.cpp

def header(text):
    text=batch.header(text)
    return once(text,'extern "C" bool CPP_gpuEarlyGrouped()', '''extern "C" bool CPP_gpuLookahead(){return std::getenv("XPU2_LOBE_LOOKAHEAD") && !std::strcmp(std::getenv("XPU2_LOBE_LOOKAHEAD"),"1");}
extern "C" bool CPP_gpuEarlyGrouped()''')

def ispc(text,bsdf_header):
    text=batch.ispc(text,bsdf_header)
    start=text.index('        uniform uint64 xpu2Tokens[16];')
    end=text.index("\n        // Loop over each lobe's samples",start)
    pack=text[start:end].replace('        uniform uint64 xpu2Tokens[16];\n','')
    helper='''extern "C" uniform bool CPP_gpuLookahead();
inline uniform bool xpu2PrepareLobe(uniform PbrTLState *uniform pbrTls,
    const varying BsdfSampler &bSampler, const varying Subpixel &sp,
    const varying PathVertex &pv, const varying BsdfLobe *uniform lobe,
    varying int lobeSampleCount, const varying IntegratorSample2D &bsdfSamples,
    uniform uint64 *uniform xpu2Tokens) {
'''+pack+'\n    return xpu2Prepared;\n}\n'
    replacement='''        uniform uint64 *uniform xpu2Tokens=&xpu2AheadTokens[lobeIndex*16];
        uniform bool xpu2Prepared=xpu2AheadPrepared[lobeIndex];
        if(!xpu2Prepared)xpu2Prepared=xpu2PrepareLobe(pbrTls,bSampler,sp,pv,lobe,lobeSampleCount,bsdfSamples,xpu2Tokens);
'''
    text=text[:start]+replacement+text[end:]
    text=once(text,'void\ndrawBsdfSamples(',helper+'\nvoid\ndrawBsdfSamples(')
    anchor='    uniform int lobeCount = BsdfSampler_getLobeCount(&bSampler);'
    prelude='''
    uniform uint64 xpu2AheadTokens[BSDF_MAX_LOBE*16];
    uniform bool xpu2AheadPrepared[BSDF_MAX_LOBE];
    for(uniform int k=0;k<BSDF_MAX_LOBE;++k)xpu2AheadPrepared[k]=false;
    // Keep all native arenas on this worker. Only copied inputs cross the queue.
    // Two eligible lobes bound advance admission to at most 32 packets.
    if(CPP_gpuEarlyEnabled(pbrTls) && CPP_gpuLookahead()) {
        varying int aheadSeed=0;
        uniform int prepared=0;
        for(uniform int k=0;k<lobeCount && prepared<2;++k){
            const varying BsdfLobe *uniform aheadLobe=BsdfSampler_getLobe(&bSampler,k);
            if(!isActive(aheadLobe))continue;
            aheadSeed+=1;
            int aheadCount=BsdfSampler_getLobeSampleCount(&bSampler,k);
            SequenceID aheadSid;
            SequenceID_init(aheadSid,(uint32_t)pv.nonMirrorDepth,sp.mPixel,aheadSeed,
                (uniform uint32_t)SequenceTypeBsdf,spIndex,sequenceID);
            IntegratorSample2D aheadSampler;IntegratorSample2D_init(aheadSampler,aheadSid);
            if(pv.nonMirrorDepth==0)aheadSampler.mSampleNumber=sp.mSubpixelIndex*aheadCount;
            else aheadSampler.mTotalSamples=aheadCount;
            xpu2AheadPrepared[k]=xpu2PrepareLobe(pbrTls,bSampler,sp,pv,aheadLobe,aheadCount,aheadSampler,&xpu2AheadTokens[k*16]);
            if(xpu2AheadPrepared[k])++prepared;
        }
    }
'''
    # Only the first occurrence belongs to drawBsdfSamples.
    at=text.index(anchor);text=text[:at]+text[at:].replace(anchor,anchor+prelude,1)
    return text


def queue(text):
    text=batch.queue(text)
    text=once(text,'    void* host=nullptr;', '    void* host=nullptr;\n    void* compactHost=nullptr;CUdeviceptr compactDevice=0;')
    text=once(text,'FlightSlot slots[4];',(HERE/'native_shared_inputs.inc').read_text()+'\nFlightSlot slots[4];')
    text=once(text,'        check(fn_cuMemHostAlloc(&s.host,512*232,0));','''
        check(fn_cuMemHostAlloc(&s.host,512*232,0));
        if(compact){check(fn_cuMemHostAlloc(&s.compactHost,8+512*108,0));check(fn_cuMemAlloc_v2(&s.compactDevice,8+512*108));}''')
    text=once(text,'        s.busy=false;','''
        if(s.compactHost && release(fn_cuMemFreeHost(s.compactHost)))s.compactHost=nullptr;
        if(s.compactDevice && release(fn_cuMemFree_v2(s.compactDevice)))s.compactDevice=0;
        s.busy=false;''')
    text=once(text,'            check(fn_cuModuleGetFunction(&kernel,module,"lambert_sample_vector"));','''
            check(fn_cuModuleGetFunction(&kernel,module,"lambert_sample_vector"));
            if(compact)check(fn_cuModuleGetFunction(&compactKernel,module,"lambert_sample_compact_vector"));''')
    old='''        check(fn_cuMemcpyHtoDAsync_v2(s.device[0],s.input(),count*96,s.stream));
        check(fn_cuMemcpyHtoDAsync_v2(s.device[1],s.lengths(),count*4,s.stream));'''
    new='''        const size_t compactBytes=compact?encodeCompact(s,input,count):0;
        const bool packed=compact && compactBytes<size_t(count)*100;
        if(packed){
            check(fn_cuMemcpyHtoDAsync_v2(s.compactDevice,s.compactHost,compactBytes,s.stream));
            ++compactBatches;compactUploadBytes+=compactBytes;lastTransferBytes=compactBytes+count*132;
        }else{
            check(fn_cuMemcpyHtoDAsync_v2(s.device[0],s.input(),count*96,s.stream));
            check(fn_cuMemcpyHtoDAsync_v2(s.device[1],s.lengths(),count*4,s.stream));
            regularUploadBytes+=count*100;lastTransferBytes=count*232;
        }'''
    text=once(text,old,new)
    text=once(text,'        void* args[]={&s.device[0],&s.device[1],&s.device[2],&s.device[3],&empty,&empty,&n};',
        '        CUdeviceptr source=packed?s.compactDevice:s.device[0];\n        void* args[]={&source,&s.device[1],&s.device[2],&s.device[3],&empty,&empty,&n};')
    text=once(text,'check(fn_cuLaunchKernel(kernel,(count+63)/64,1,1,64,1,1,0,s.stream,args,nullptr));',
        'check(fn_cuLaunchKernel(packed?compactKernel:kernel,(count+63)/64,1,1,64,1,1,0,s.stream,args,nullptr));')
    return once(text,'stagingBytes+=static_cast<unsigned long long>(f.count)*232;', 'stagingBytes+=device.lastTransferBytes;')

def profile(text):
    text=batch.profile(text)
    return once(text,'    shaderQueue.reset();',r'''    if(const char* name=std::getenv("XPU2_WORK_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        std::fprintf(f,"{\"compact_batches\":%llu,\"compact_upload_bytes\":%llu,\"regular_upload_bytes\":%llu}\n",d.compactBatches,d.compactUploadBytes,d.regularUploadBytes);std::fclose(f);
    }
    shaderQueue.reset();''')

def cuda(text):
    start=text.index('template<bool Vector> __device__ void sampleLambert(')
    body=text.index('    for(U i=0;i<96;++i)dst[i]=src[i];',start)
    text=text[:start]+'''template<bool Vector> __device__ void shadeSample(const unsigned char* src,unsigned char* dst,U* result,U length) {
'''+text[body:]
    text=once(text,'lengths[id]!=96','length!=96')
    anchor='extern "C" __global__ void lambert_sample('
    wrappers='''template<bool Vector> __device__ void sampleLambert(const unsigned char* input,const U* lengths,
    unsigned char* output,U* results,const float*,const float*,U count) {
    U id=blockIdx.x*blockDim.x+threadIdx.x;if(id>=count)return;
    shadeSample<Vector>(input+id*96,output+id*96,results+id*9,lengths[id]);
}
extern "C" __global__ void lambert_sample_compact_vector(const unsigned char* input,const U*,
    unsigned char* output,U* results,const float*,const float*,U count) {
    U id=blockIdx.x*blockDim.x+threadIdx.x;if(id>=count)return;
    const U* packed=reinterpret_cast<const U*>(input);
    U words[24]={};U index=packed[2+id*3];
    if(packed[0]==count && count<=512 && packed[1]<=count && index<packed[1]){
        const U* common=packed+2+count*3+index*24;
        for(U i=0;i<24;++i)words[i]=common[i];
        words[11]=packed[2+id*3+1];words[12]=packed[2+id*3+2];
    }
    shadeSample<true>(reinterpret_cast<const unsigned char*>(words),output+id*96,results+id*9,96);
}
'''
    return once(text,anchor,wrappers+anchor)
