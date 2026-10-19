from pathlib import Path
import shutil
from .native_gpu_paths import once

def patch(out):
 shutil.copyfile(Path(__file__).with_name('resident_records.h'),out/'resident_records.h')
 p=out/'prepared_records.h';s=p.read_text()
 s=once(s,'unsigned count=0;','unsigned poolSlot=0,count=0;')
 s=once(s,'for(int i=0;i<capacity;++i)slots_.push_back(std::make_shared<Group>());','for(int i=0;i<capacity;++i){slots_.push_back(std::make_shared<Group>());slots_.back()->poolSlot=unsigned(i);}')
 p.write_text(s)
 p=out/'early_queue.inc';s=p.read_text();s='#include "resident_records.h"\n'+s
 s=once(s,'    bool busy=false;','    void* residentHost=nullptr;CUdeviceptr residentUpload=0,residentTable=0;\n    xpu2::resident::Cache residentCache;\n    bool busy=false;')
 s=once(s,'CUfunction compactKernel=nullptr;', 'CUfunction compactKernel=nullptr,residentKernel=nullptr;\nbool resident=std::getenv("XPU2_RESIDENT_RECORDS") && !std::strcmp(std::getenv("XPU2_RESIDENT_RECORDS"),"1");\nbool residentFlush=std::getenv("XPU2_RESIDENT_FLUSH")!=nullptr,residentStale=std::getenv("XPU2_RESIDENT_STALE")!=nullptr;\nunsigned long long residentFallback=0;')
 s=once(s,'\n        const size_t sizes[]={512*96,512*4,512*96,512*36};','''
        if(resident){check(fn_cuMemHostAlloc(&s.residentHost,xpu2::resident::maxWords*4,0));
            check(fn_cuMemAlloc_v2(&s.residentUpload,xpu2::resident::maxWords*4));
            check(fn_cuMemAlloc_v2(&s.residentTable,xpu2::resident::slots*xpu2::resident::entryWords*4));}
        const size_t sizes[]={512*96,512*4,512*96,512*36};''')
 s=once(s,'        s.busy=false;','''        if(s.residentHost && release(fn_cuMemFreeHost(s.residentHost)))s.residentHost=nullptr;
        if(s.residentUpload && release(fn_cuMemFree_v2(s.residentUpload)))s.residentUpload=0;
        if(s.residentTable && release(fn_cuMemFree_v2(s.residentTable)))s.residentTable=0;
        s.busy=false;''')
 s=once(s,'bool startFlight(unsigned index,unsigned limit,const float* input,int count) {','bool startFlight(unsigned index,unsigned limit,const float* input,int count,const xpu2::resident::View* views=nullptr) {')
 s=once(s,'        const size_t compactBytes=compact?encodeCompact(s,input,count):0;', '''        const bool residentBatch=resident && views;
        const size_t residentBytes=residentBatch?s.residentCache.encode(static_cast<U*>(s.residentHost),views,unsigned(count)/8,residentFlush,residentStale):0;
        if(resident && !residentBatch)++residentFallback;
        const size_t compactBytes=compact && !residentBatch?encodeCompact(s,input,count):0;''')
 s=once(s,'        if(packed){\n            check(fn_cuMemcpyHtoDAsync_v2', '''        if(residentBatch){
            check(fn_cuMemcpyHtoDAsync_v2(s.residentUpload,s.residentHost,residentBytes,s.stream));
            lastTransferBytes=residentBytes+count*(leanWire?36:132);
        }else if(packed){
            check(fn_cuMemcpyHtoDAsync_v2''')
 s=once(s,'CUdeviceptr source=packed?s.compactDevice:s.device[0];','CUdeviceptr source=residentBatch?s.residentUpload:packed?s.compactDevice:s.device[0];\n        CUdeviceptr table=residentBatch?s.residentTable:0;')
 s=once(s,'void* args[]={&source,&s.device[1],&s.device[2],&s.device[3],&empty,&empty,&n};','void* args[]={&source,&s.device[1],&s.device[2],&s.device[3],&table,&empty,&n};')
 s=once(s,'fn_cuLaunchKernel(packed?compactKernel:kernel,','fn_cuLaunchKernel(residentBatch?residentKernel:packed?compactKernel:kernel,')
 s=once(s,'            if(compact)check(fn_cuModuleGetFunction(&compactKernel,module,"lambert_sample_compact_vector"));','            if(compact)check(fn_cuModuleGetFunction(&compactKernel,module,"lambert_sample_compact_vector"));\n            if(resident)check(fn_cuModuleGetFunction(&residentKernel,module,"lambert_sample_resident_vector"));')
 s=once(s,'                const bool started=device.startFlight(i,flights,f.inputData(),f.count);', '''                xpu2::resident::View views[64];
                const bool allPrepared=device.resident && std::all_of(f.requests.begin(),f.requests.end(),[](const Ticket& r){return r->prepared && r->count==8;});
                if(allPrepared)for(unsigned j=0;j<f.requests.size();++j){const auto& r=f.requests[j];views[j]={r->prepared.get(),r->prepared->poolSlot,r->preparedPacket};}
                const bool started=device.startFlight(i,flights,f.inputData(),f.count,allPrepared?views:nullptr);''')
 p.write_text(s)
 p=out/'native_gpu_shading.h';s=p.read_text();s=once(s,'    shaderQueue->preparedPool.report();',r'''    if(const char* name=std::getenv("XPU2_RESIDENT_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        uint64_t batches=0,updates=0,reused=0,descriptors=0,bytes=0;
        for(const auto& slot:d.slots){const auto& c=slot.residentCache;batches+=c.batches;updates+=c.updates;reused+=c.reusedGroups;descriptors+=c.descriptors;bytes+=c.bytes;}
        std::fprintf(f,"{\"enabled\":%s,\"flush\":%s,\"stale\":%s,\"batches\":%llu,\"updates\":%llu,\"reused_groups\":%llu,\"descriptors\":%llu,\"upload_bytes\":%llu,\"fallback_batches\":%llu}\n",d.resident?"true":"false",d.residentFlush?"true":"false",d.residentStale?"true":"false",(unsigned long long)batches,(unsigned long long)updates,(unsigned long long)reused,(unsigned long long)descriptors,(unsigned long long)bytes,d.residentFallback);std::fclose(f);
    }
    shaderQueue->preparedPool.report();''');p.write_text(s)
