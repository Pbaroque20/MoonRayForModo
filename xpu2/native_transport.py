'''Opt-in reusable batch ownership in the native two-flight dispatcher.'''
from pathlib import Path
from . import native_context as context
from .native_gpu_paths import once
HERE=Path(__file__).resolve().parent
adapter=context.adapter
cpp=context.cpp
header=context.header
cuda=context.cuda
ispc=context.ispc
multisampler=context.multisampler
shadow_header=context.shadow_header
driver=context.driver

def queue(text):
    text=context.queue(text)
    start=text.index('    // Each slot owns its requests and scratch vectors')
    end=text.index('    void work() {',start)
    text=text[:start]+(HERE/'native_transport_worker.inc').read_text()+'\n'+text[end:]
    text=once(text,'void finishFlight(unsigned index,float* input,float* output,int count,bool failed)', 'void finishFlight(unsigned index,const float* input,float* output,int count,bool failed)')
    return '#include "batch_transport.h"\n'+text

def profile(text):
    text=context.profile(text)
    return once(text,'    shaderQueue.reset();',r'''    if(const char* name=std::getenv("XPU2_TRANSPORT_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        const auto& q=*shaderQueue;
        std::fprintf(f,"{\"enabled\":%s,\"packed\":%llu,\"retired\":%llu,\"failed\":%llu,\"discarded\":%llu,\"bypassed\":%llu,\"active\":%u,\"pack_ns\":%llu,\"retire_ns\":%llu}\n",
            q.transport?"true":"false",q.transportPacks,q.transportRetired,q.transportFailed,q.transportDiscarded,q.transportBypass,q.transportActive,q.packNs,q.retireNs);std::fclose(f);
    }
    shaderQueue.reset();''')
