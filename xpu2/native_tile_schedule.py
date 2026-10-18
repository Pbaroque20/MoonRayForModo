"""Opt-in native packet locality, generated without changing shared sources."""
from . import native_gpu_early as early
from .native_gpu_paths import once
adapter=early.adapter
cpp=early.cpp

def header(text):
    text=once(text,'CPP_gpuEarlySubmit(const float* input)', 'CPP_gpuEarlySubmit(const float* input,const uint32_t* pixels)')
    return once(text,'submit(input,empty,8,epoch)', 'submit(input,empty,8,epoch,{},pixels)')

def ispc(text,bsdf_header):
    text=early.ispc(text,bsdf_header)
    text=once(text,'CPP_gpuEarlySubmit(const uniform float *uniform input)', 'CPP_gpuEarlySubmit(const uniform float *uniform input,const uniform uint32 *uniform pixels)')
    text=once(text,'                uniform float xpu2Input[192];', '''                uniform uint32 xpu2Pixels[8];
                for(uniform int k=0;k<8;++k)xpu2Pixels[k]=0xffffffff;
                uniform float xpu2Input[192];''')
    text=once(text,'                        uniform int b=lane*24;', '                        xpu2Pixels[lane]=extract(sp.mPixel,lane);\n                        uniform int b=lane*24;')
    return once(text,'CPP_gpuEarlySubmit(xpu2Input)', 'CPP_gpuEarlySubmit(xpu2Input,xpu2Pixels)')

def queue(text):
    text=early.queue(text)
    text=once(text,'#include <atomic>', '#include "native_tile_policy.h"\n#include <atomic>')
    text=once(text,'    float input[8*24],output[8*8];\n    int count=0;', '    float input[8*24],output[8*8];\n    uint32_t tile=xpu2tile::unknown;\n    uint64_t queuedClaim=0;\n    int count=0;')
    text=once(text,'    unsigned capacity=32,coalesceUs=0;', '''    xpu2tile::Policy tilePolicy;
    unsigned batchLimit=64;
    unsigned long long mixedPackets=0,unknownPackets=0,selectionNs=0,deviceNs=0,idleNs=0,stagingBytes=0;
    unsigned capacity=32,coalesceUs=0;''')
    text=once(text,'    Queue() {', '''    Queue() {
        const char* tp=std::getenv("XPU2_TILE_POLICY");
        tilePolicy.neighbor=tp && !std::strcmp(tp,"neighbor");
        const char* bl=std::getenv("XPU2_TILE_BATCH_LIMIT");
        if(bl)batchLimit=std::min(64,std::max(1,std::atoi(bl)));''')
    text=once(text,'std::shared_ptr<const void> resources={})', 'std::shared_ptr<const void> resources={},const uint32_t* pixels=nullptr)')
    text=once(text,'        request->owner=ownerToken;', '''        bool mixedTile=false;request->tile=xpu2tile::tileFor(pixels,mixedTile);
        mixedPackets+=mixedTile;unknownPackets+=request->tile==xpu2tile::unknown;
        request->queuedClaim=tilePolicy.claims;
        request->owner=ownerToken;''')
    text=once(text,'                available.wait(lock,[&]{return stopping || !pending.empty();});', '''                const auto idleStart=std::chrono::steady_clock::now();
                available.wait(lock,[&]{return stopping || !pending.empty();});
                idleNs+=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-idleStart).count();''')
    text=once(text,'                while(!pending.empty() && batch.size()<64){batch.push_back(pending.front());pending.pop_front();}', '''                const auto selectionStart=std::chrono::steady_clock::now();
                while(!pending.empty() && batch.size()<batchLimit){
                    const auto chosen=tilePolicy.choose(pending);
                    batch.push_back(pending[chosen]);pending.erase(pending.begin()+chosen);
                }
                selectionNs+=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-selectionStart).count();''')
    text=once(text,'            bool failure=false;', '            const auto deviceStart=std::chrono::steady_clock::now();\n            bool failure=false;')
    text=once(text,'                ++merged;', '''                deviceNs+=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-deviceStart).count();
                // Bridge: 96-byte input H2D, then input + 36-byte results D2H, plus 4-byte length per lane.
                stagingBytes+=static_cast<unsigned long long>(count)*232;
                ++merged;''')
    return text

def profile(text):
    return once(text,'    if(shaderQueue->retainedAsync)throw', r'''    if(const char* name=std::getenv("XPU2_NATIVE_TILE_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        const auto& q=*shaderQueue;const auto& p=q.tilePolicy;
        std::fprintf(f,"{\"neighbor\":%s,\"batch_limit\":%u,\"claims\":%llu,\"local\":%llu,\"shared\":%llu,\"aged\":%llu,\"reordered\":%llu,\"inspected\":%llu,\"switches\":%llu,\"mixed_packets\":%llu,\"unknown_packets\":%llu,\"selection_ns\":%llu,\"device_ns\":%llu,\"idle_ns\":%llu,\"staging_bytes\":%llu,\"batches\":%llu,\"queue_full\":%llu,\"max_queue\":%llu}\n",
          p.neighbor?"true":"false",q.batchLimit,(unsigned long long)p.claims,(unsigned long long)p.local,(unsigned long long)p.shared,(unsigned long long)p.aged,(unsigned long long)p.reordered,(unsigned long long)p.inspected,(unsigned long long)p.switches,q.mixedPackets,q.unknownPackets,q.selectionNs,q.deviceNs,q.idleNs,q.stagingBytes,q.merged,q.full,q.maxQueue);std::fclose(f);
    }
    if(shaderQueue->retainedAsync)throw''')
