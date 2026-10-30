"""Broaden owner-thread preparation to mixed-depth chunks without moving native state."""
from . import native_owned_chunks as base
from .native_gpu_paths import once
adapter=base.adapter
cpp=base.cpp
queue=base.queue
profile=base.profile
cuda=base.cuda
shadow_header=base.shadow_header
driver=base.driver
ispc=base.ispc
multisampler=base.multisampler
bundled=base.bundled

def header(text):
    text=base.header(text)
    text=once(text,'inline unsigned ownedDepth=0;', '''inline unsigned ownedDepth=0;
inline bool ownedMixed=false;
inline std::atomic<uint64_t> ownedHandlers{0},ownedEligibleHandlers{0},ownedEligibleEntries{0};''')
    text=once(text,'inline void ownedReset(){','''inline void ownedReset(){
    const char* mixed=std::getenv("XPU2_OWNED_MIXED");ownedMixed=mixed && !std::strcmp(mixed,"1");
    ownedHandlers=0;ownedEligibleHandlers=0;ownedEligibleEntries=0;''')
    text=once(text,'        std::fprintf(f,"{\\\"depth\\\":%u,', '        std::fprintf(f,"{\\\"mixed\\\":%s,\\\"handlers\\\":%llu,\\\"eligible_handlers\\\":%llu,\\\"eligible_entries\\\":%llu,\\\"depth\\\":%u,')
    text=once(text,'",ownedDepth,','",ownedMixed?"true":"false",(unsigned long long)ownedHandlers.load(),(unsigned long long)ownedEligibleHandlers.load(),(unsigned long long)ownedEligibleEntries.load(),ownedDepth,')
    return text+'''
extern "C" bool CPP_gpuOwnedMixed(){return xpu2::nativepath::ownedMixed;}
extern "C" void CPP_gpuOwnedSeen(unsigned entries,bool eligible){
    using namespace xpu2::nativepath;
    ++ownedHandlers;if(eligible){++ownedEligibleHandlers;ownedEligibleEntries+=entries;}
}
'''

def handler(text):
    text=base.handler(text)
    text=once(text,'extern "C" unsigned CPP_gpuOwnedChunks(void* tls);','''extern "C" unsigned CPP_gpuOwnedChunks(void* tls);
extern "C" bool CPP_gpuOwnedMixed();
extern "C" void CPP_gpuOwnedSeen(unsigned,bool);''')
    text=once(text,'numEntries>=128 && !handlePresenceContinue','numEntries>64 && !handlePresenceContinue')
    text=once(text,'        for(unsigned i=0;i<numEntries && xpu2OwnedEligible;++i){', '        if(!CPP_gpuOwnedMixed())for(unsigned i=0;i<numEntries && xpu2OwnedEligible;++i){')
    text=once(text,'    if(xpu2OwnedEligible){\n        struct OwnedChunk', '    CPP_gpuOwnedSeen(numEntries,xpu2OwnedEligible);\n    if(xpu2OwnedEligible){\n        struct OwnedChunk')
    return text
