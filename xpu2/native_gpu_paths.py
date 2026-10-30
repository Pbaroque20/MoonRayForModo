"""Strict copied-source hooks for owned native indirect GPU shading."""
from pathlib import Path
HERE=Path(__file__).resolve().parent

def once(text,old,new):
    if text.count(old)!=1:raise ValueError('Native GPU hook drift: '+old[:90])
    return text.replace(old,new)

def adapter(text):
    text=once(text,'#include "native_path_restore.h"','#include "native_path_restore.h"\n#include "native_gpu_shading.h"')
    text=once(text,'struct Path {','struct Path {\n    std::shared_ptr<Shader> shader;\n    unsigned shaderLane=0;')
    text=once(text,'    bool draining=false;','    bool draining=false,cpuWindow=false;')
    text=once(text,'    r.mSequenceID=p.sequence;', '    applyShader(r,p);\n    r.mSequenceID=p.sequence;')
    text=once(text,'    fixed=fixedSamples;', '    if(!std::getenv("XPU2_NATIVE_GPU_PATHS")){enabled=false;return;}\n    shaderBegin();\n    fixed=fixedSamples;')
    text=once(text,'    if(s->draining||s->paths.empty())return 0;', '    if(s->cpuWindow){--activeCpu;s->cpuWindow=false;}\n    if(s->draining||s->paths.empty())return 0;')
    text=once(text,'if(tls->isCanceled()){cancelled+=s->paths.size();', 'if(tls->isCanceled()){cancelShaders(s->paths);cancelled+=s->paths.size();')
    text=once(text,'    for(unsigned count:sizes){\n        SCOPED_MEM', '''    for(unsigned count:sizes){
        for(unsigned i=0;i<count;++i)if(paths[offset+i].shader && !resolveShader(tls,*paths[offset+i].shader,epoch)){
            cancelShaders(paths);cancelled+=paths.size()-offset;return unsigned(offset);
        }
        SCOPED_MEM''')
    text=once(text,'bool defer(pbr::TLState* tls,unsigned n,pbr::RayState** rays){', 'bool defer(pbr::TLState* tls,unsigned n,pbr::RayState** rays,const float* payload,const unsigned* indices){')
    text=once(text,'    if(!enabled||!n)return false;', '    if(!enabled||!n||!payload)return false;')
    text=once(text,'    s->pendingCount=unsigned(s->paths.size());', '    prepareShaders(s->paths,s->paths.size()-n,n,payload,indices,epoch);\n    s->pendingCount=unsigned(s->paths.size());')
    text=once(text,'    if(immediate)drain(tls);return true;', '    ++shaderReturns;if(!s->cpuWindow){s->cpuWindow=true;++activeCpu;}\n    if(immediate)drain(tls);return true;')
    text=once(text,'void finish(){', 'bool defer(pbr::TLState*,unsigned,pbr::RayState**){return false;}\nbool gpuEnabled(){return enabled&&fixed;}\nvoid finish(){')
    text=once(text,'for(auto& kv:owners){cancelled+=kv.second->paths.size();kv.second->paths.clear();}', 'for(auto& kv:owners){if(kv.second->cpuWindow)--activeCpu;cancelShaders(kv.second->paths);cancelled+=kv.second->paths.size();kv.second->paths.clear();}\n    shaderFinish(epoch);')
    return text

def cpp(text):
    start=text.index('void\nCPP_addRayQueueEntries(');end=text.index('\nvoid\nCPP_addOcclusionQueueEntries(',start)
    clone=text[start:end].replace('void\nCPP_addRayQueueEntries(', 'extern "C" void\nCPP_addGpuRayQueueEntries(',1)
    clone=once(clone,'unsigned numRayStates, const unsigned *indices)', 'unsigned numRayStates, const unsigned *indices, const float *payload)')
    clone=once(clone,'    pbrTls->addRayQueueEntries(numRayStates, rayStates);', '    if (!xpu2::nativepath::defer(pbrTls,numRayStates,rayStates,payload,indices))\n        pbrTls->addRayQueueEntries(numRayStates, rayStates);')
    return once(text,'namespace moonray {','#include "native_gpu_paths.inc"\n\nnamespace moonray {').replace(text[start:end],text[start:end]+'\nextern "C" bool CPP_gpuPathsEnabled(){return xpu2::nativepath::gpuEnabled();}\n'+clone,1)

def ispc(text):
    declarations='''#include <moonray/rendering/shading/ispc/bsdf/BsdfLambert.isph>
extern "C" uniform bool CPP_gpuPathsEnabled();
extern "C" void CPP_addGpuRayQueueEntries(uniform PbrTLState *uniform tls, const varying RayState *uniform rays, uniform uint32_t count, const uniform uint32_t *uniform indices, const uniform float *uniform payload);
'''
    text=once(text,'// Returns the number of BundledOcclRay entries filled',declarations+'\n// Returns the number of BundledOcclRay entries filled')
    start=text.index('void\naddIndirectOrDirectVisibleContributionsBundled(');end=text.index('\nvoid\ncomputeRadianceBsdfMultiSampler',start)
    part=text[start:end]
    part=once(part,'    uniform uint32_t numSpawnedRays = 0;', '    uniform uint32_t numSpawnedRays = 0;\n    uniform bool xpu2Enabled=CPP_gpuPathsEnabled();\n    uniform float *uniform xpu2Payload=xpu2Enabled ? (uniform float *uniform)Arena_allocArray(arena,sampleCount*VLEN*40,sizeof(uniform float)) : NULL;')
    part=once(part,'            snapshotLaneUtilization(pbrTls->mStatistics, STATS_VEC_INDIRECT_F);', (HERE/'native_gpu_pack.ispc.inc').read_text(encoding='utf-8')+'\n            snapshotLaneUtilization(pbrTls->mStatistics, STATS_VEC_INDIRECT_F);')
    old='        CPP_addRayQueueEntries(pbrTls, spawnedRays, numSpawnedRays,\n                               spawnedRayIndices);'
    part=once(part,old,'        if(xpu2Enabled) CPP_addGpuRayQueueEntries(pbrTls,spawnedRays,numSpawnedRays,spawnedRayIndices,xpu2Payload);\n        else '+old.lstrip())
    return text[:start]+part+text[end:]
