'''Isolate native queue families and admit only GPU-sized ray work when requested.'''
from . import native_material_context as context
from .native_gpu_paths import once
adapter=context.adapter
cpp=context.cpp
queue=context.queue
profile=context.profile
cuda=context.cuda
ispc=context.ispc
multisampler=context.multisampler

def header(text):
    text=context.header(text)
    text=once(text, 'auto count=tls->flushLocalQueues();', r'''const char* scope=std::getenv("XPU2_HELP_SCOPE");
    const bool localOnly=scope && !std::strcmp(scope,"local");
    const bool allQueues=!scope || !std::strcmp(scope,"all");
    unsigned count=(localOnly || allQueues)?tls->flushLocalQueues():0;''')
    text=once(text, 'if(!tls->isCanceled())count+=', 'if(!localOnly && !tls->isCanceled())count+=')
    return text+r'''
extern "C" int xpu2MaterialHelpScope(){
    if(!xpu2::nativepath::helpingMaterial)return 0;
    const char* scope=std::getenv("XPU2_HELP_SCOPE");
    if(!scope)return 0;
    if(!std::strcmp(scope,"rays"))return 1;
    if(!std::strcmp(scope,"shadows"))return 2;
    if(!std::strcmp(scope,"ready"))return 3;
    return 0;
}
'''

def ray_header(text):
    return once(text, '    unsigned getMemoryUsed() const', r'''    // Only read the owning CPU thread's queue. Other threads retain the
    // native GPU admission guard; this is not a device reservation.
    bool xpu2GpuReady(mcrt_common::ThreadLocalState *tls) const
    {
        return mCPUThreadQueueNumQueued[tls->mThreadIdx] > 1024 &&
               mNumThreadsUsingGPU.load() < 5;
    }

'''+ '    unsigned getMemoryUsed() const')

def driver(text):
    text='extern "C" int xpu2MaterialHelpScope();\n'+text
    return once(text, r'''        numFlushed += mXPUOcclusionRayQueue->flush(tls, arena);
        numFlushed += mXPURayQueue->flush(tls, arena);''', r'''        const int scope=xpu2MaterialHelpScope();
        if(scope!=1 && (scope!=3 || mXPUOcclusionRayQueue->xpu2GpuReady(tls)))
            numFlushed += mXPUOcclusionRayQueue->flush(tls, arena);
        if(scope!=2 && (scope!=3 || mXPURayQueue->xpu2GpuReady(tls)))
            numFlushed += mXPURayQueue->flush(tls, arena);''')
