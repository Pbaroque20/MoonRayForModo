'''Opt-in native shadow work during a pending GPU material sample dependency.'''
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
    text=once(text, 'auto count=tls->flushLocalQueues();', 'unsigned count=0; // Do not reorder intersection/shading queues or film queues.')
    return text+r'''
extern "C" bool xpu2ShadowHelpActive(){
    return xpu2::nativepath::helpingMaterial;
}
'''

def shadow_header(text):
    text=once(text, '#pragma once', '#pragma once\nextern "C" bool xpu2ShadowHelpActive();')
    return once(text,
        'if ((mNumThreadsUsingGPU.load() < maxThreads) && numRays > 1024) {',
        '''// A scoped helper keeps shadow traversal on the GPU. Outside that
        // scope the native size threshold and busy-device guard are unchanged.
        if ((mNumThreadsUsingGPU.load() < maxThreads) &&
            (numRays > 1024 || xpu2ShadowHelpActive())) {''')

def driver(text):
    text='extern "C" bool xpu2ShadowHelpActive();\n'+text
    return once(text,
        '        numFlushed += mXPURayQueue->flush(tls, arena);',
        '''        // A pending material dependency may help shadows only. Normal
        // frame drains still flush both queues, including small remaining tails.
        if(!xpu2ShadowHelpActive())numFlushed += mXPURayQueue->flush(tls, arena);''')
