"""Two owner-thread native chunks; original per-chunk shading and integration sizes."""
from pathlib import Path
from . import native_integration_profile as base
from .native_gpu_paths import once
HERE=Path(__file__).resolve().parent
adapter=base.adapter
cpp=base.cpp
queue=base.queue
profile=base.profile
cuda=base.cuda
shadow_header=base.shadow_header
driver=base.driver
ispc=base.ispc
multisampler=base.multisampler

def header(text):
    text=base.header(text)
    text=once(text,'inline void integrationReset(){','inline void ownedReset();inline void ownedFinish();\ninline void integrationReset(){ownedReset();')
    text=once(text,'inline void integrationFinish(){','inline void integrationFinish(){ownedFinish();')
    text=once(text,'struct WindowScope {','struct WindowScope {\n    std::thread::id ownerThread=std::this_thread::get_id();bool owned=false;')
    text=once(text,'inline thread_local WindowScope* currentWindow=nullptr;','inline thread_local WindowScope* currentWindow=nullptr;\ninline thread_local bool ownedBound=false;\ninline unsigned ownedDepth=0;\ninline std::atomic<uint64_t> ownedPrepared{0},ownedResumed{0},ownedFinished{0},ownedCanceled{0};')
    text=once(text,'    if(!windowSize || currentWindow || !CPP_gpuEarlyEnabled(tls) || tls->isCanceled())return 0;', '''    if(ownedBound){
        if(!currentWindow || !currentWindow->owned || currentWindow->ownerThread!=std::this_thread::get_id() || currentWindow->revision!=epoch)throw std::logic_error("Invalid owned chunk resume");
        ownedBound=false;++ownedResumed;return reinterpret_cast<uint64_t>(currentWindow);
    }
    if(!windowSize || currentWindow || !CPP_gpuEarlyEnabled(tls) || tls->isCanceled())return 0;''')
    text=once(text,'    delete currentWindow;currentWindow=nullptr;--windowActive;','    if(currentWindow->owned)++ownedFinished;\n    delete currentWindow;currentWindow=nullptr;--windowActive;')
    return text+'\n'+(HERE/'native_owned_chunks.inc').read_text(encoding='utf-8')

DECL='''
extern "C" uniform bool CPP_gpuOwnedWindowBound();
extern "C" void CPP_gpuOwnedWindowDetach(uniform uint64 handle);
'''
def bundled(text):
    text=base.bundled(text)
    text=once(text,'// Restrict speculation to full primary SIMD blocks',DECL+'\n// Restrict speculation to full primary SIMD blocks')
    text=once(text,'uniform uint64 xpu2Window)','uniform uint64 xpu2Window,uniform bool xpu2Owned)')
    text=once(text,'if(xpu2Window && i%CPP_gpuWindowSize()==0)', 'if(xpu2Window && !xpu2Owned && i%CPP_gpuWindowSize()==0)')
    text=once(text,'    uniform uint64 window=CPP_gpuWindowBegin(pbrTls);','    uniform bool owned=CPP_gpuOwnedWindowBound();\n    uniform uint64 window=CPP_gpuWindowBegin(pbrTls);')
    text=once(text,'presences,window);','presences,window,owned);')
    return text+'''
export uniform uint64 XPU2_prepareOwnedChunk(const uniform PathIntegrator *uniform integrator,
    uniform PbrTLState *uniform tls,uniform unsigned numEntries,varying RayState *uniform rayStates,
    const varying Intersection *uniform isects,const varying Bsdf *uniform bsdfs,
    const varying float *uniform presences){
    uniform uint64 handle=CPP_gpuWindowBegin(tls);
    if(!handle)return 0;
    uniform unsigned blocks=(numEntries+VLEN-1)/VLEN;
    for(uniform unsigned i=0;i<blocks;++i){
        CPP_gpuWindowRecord(handle,i);
        if((i+1)*VLEN<=numEntries)
            xpu2WindowPrepare(integrator,tls,rayStates[i],isects[i],bsdfs[i],presences[i]);
    }
    CPP_gpuWindowPublish(handle);
    CPP_gpuOwnedWindowDetach(handle);
    return handle;
}
'''

def handler(text):
    text=once(text,'namespace moonray {', '''extern "C" unsigned CPP_gpuOwnedChunks(void* tls);
extern "C" uint64_t XPU2_prepareOwnedChunk(const void*,void*,unsigned,void*,const void*,const void*,const float*);
extern "C" void CPP_gpuOwnedWindowBind(uint64_t);
extern "C" void CPP_gpuOwnedWindowCancel(uint64_t);
namespace moonray {''')
    start=text.index('    while (numRemaining) {');stop=text.index('\n    MNRY_ASSERT(sortedEntries == endEntry);',start)
    original=text[start:stop]
    split=original.index('        // Cutout materials')
    finish=original.index('        // Move on to next block of inputs.')
    prepare=original[len('    while (numRemaining) {'):split]
    integrate=original[split:finish]
    call='                                          isectsSOA, bsdfv, lightList, lightFilterLists, lightAcc, presences);'
    integrate=once(integrate,call,call+'\n        chunk.window=0;')
    declarations='''
    bool xpu2OwnedEligible=CPP_gpuOwnedChunks(pbrTls)==2 && shadingWorkloadChunkSize==64 && numEntries>=128 && !handlePresenceContinue;
    // This first experiment is restricted to primary rays in the two qualified material classes.
    if(xpu2OwnedEligible){
        const auto& name=material.getSceneClass().getName();
        xpu2OwnedEligible=name=="DwaBaseMaterial" || name=="UsdPreviewSurface";
        for(unsigned i=0;i<numEntries && xpu2OwnedEligible;++i){
            const RayState* rs=baseRayState+sortedEntries[i].mRsIdx;
            xpu2OwnedEligible=rs->mRay.getDepth()==0 && rs->mPathVertex.nonMirrorDepth==0;
        }
    }
    if(xpu2OwnedEligible){
        struct OwnedChunk {
            shading::Intersectionv* isects;shading::Bsdfv* bsdf;RayStatev* soa;
            RayState** rays;float* presence;SortedEntry* entries=nullptr;unsigned size=0;
            const LightPtrList* lights=nullptr;const LightFilterLists* filters=nullptr;const LightAccelerator* acc=nullptr;
            uint64_t window=0;bool ready=false;
            ~OwnedChunk(){if(window)CPP_gpuOwnedWindowCancel(window);}
        } chunks[2];
        for(unsigned i=0;i<2;++i){
            auto& c=chunks[i];
            c.isects=i?arena->allocArray<shading::Intersectionv>(numWorkloadChunkBlocks,CACHE_LINE_SIZE):isectsSOA;
            c.bsdf=i?arena->allocArray<shading::Bsdfv>(numWorkloadChunkBlocks,CACHE_LINE_SIZE):bsdfv;
            c.soa=i?arena->allocArray<RayStatev>(numWorkloadChunkBlocks,CACHE_LINE_SIZE):rayStatesSOA;
            c.presence=i?arena->allocArray<float>(shadingWorkloadChunkSize):presences;
            c.rays=arena->allocArray<RayState*>(shadingWorkloadChunkSize);
        }
        auto prepareChunk=[&](OwnedChunk& chunk){
            auto* isectsSOA=chunk.isects;auto* bsdfv=chunk.bsdf;auto* rayStatesSOA=chunk.soa;
            auto* presences=chunk.presence;auto** rayStates=chunk.rays;
            chunk.ready=false;chunk.entries=sortedEntries;
'''+prepare+'''
            chunk.size=workLoadSize;chunk.lights=lightList;chunk.filters=lightFilterLists;chunk.acc=lightAcc;
            bool opaque=true;for(unsigned i=0;i<workLoadSize;++i)opaque=opaque && presences[i]==1.f;
            if(opaque){
                convertAOSRayStatesToSOA(pbrTls,workLoadSize,baseRayState,rayStatesSOA,&sortedEntries[0].mRsIdx);
                EXCL_ACCUMULATOR_PROFILE(pbrTls,EXCL_ACCUM_INTEGRATION);
                pbrTls->startIspcAccumulator();
                chunk.window=XPU2_prepareOwnedChunk(fs.mIntegrator,pbrTls,workLoadSize,rayStatesSOA,isectsSOA,bsdfv,presences);
                pbrTls->stopIspcAccumulator();
            }
            sortedEntries+=workLoadSize;chunk.ready=true;
        };
        auto finishChunk=[&](OwnedChunk& chunk){
            auto* isectsSOA=chunk.isects;auto* bsdfv=chunk.bsdf;auto* rayStatesSOA=chunk.soa;
            auto* presences=chunk.presence;auto** rayStates=chunk.rays;auto* sortedEntries=chunk.entries;
            unsigned workLoadSize=chunk.size;auto* lightList=chunk.lights;
            auto* lightFilterLists=chunk.filters;auto* lightAcc=chunk.acc;
            if(chunk.window)CPP_gpuOwnedWindowBind(chunk.window);
'''+integrate+'''
            chunk.ready=false;
        };
        while(numRemaining){
            unsigned prepared=0;
            for(;prepared<2 && numRemaining;++prepared){
                prepareChunk(chunks[prepared]);
                if(!chunks[prepared].ready)return;
            }
            for(unsigned i=0;i<prepared;++i){
                CHECK_CANCELLATION(pbrTls,return);
                finishChunk(chunks[i]);
            }
        }
    }else{
'''+original+'\n    }\n'
    return text[:start]+declarations+text[stop:]
