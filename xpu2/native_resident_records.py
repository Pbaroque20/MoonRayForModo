from pathlib import Path
import shutil
from .native_gpu_paths import once

def patch(out):
 for name in ('resident_records.h','resident_wire.h'):shutil.copyfile(Path(__file__).with_name(name),out/name)
 p=out/'prepared_records.h';s=p.read_text()
 s=once(s,'unsigned count=0;','unsigned poolSlot=0,count=0;')
 s=once(s,'for(int i=0;i<capacity;++i)slots_.push_back(std::make_shared<Group>());','for(int i=0;i<capacity;++i){slots_.push_back(std::make_shared<Group>());slots_.back()->poolSlot=unsigned(i);}')
 p.write_text(s)
 p=out/'early_queue.inc';s=p.read_text();s='#include "resident_records.h"\n'+s
 s=once(s,'    bool busy=false;','    void* residentHost=nullptr;CUdeviceptr residentUpload=0,residentTable=0;\n    xpu2::resident::Cache residentCache;\n    xpu2::resident::View residentViews[xpu2::resident::maxPackets];\n    bool descriptorOnly=false;\n    bool busy=false;')
 s=once(s,'CUfunction compactKernel=nullptr;', 'CUfunction compactKernel=nullptr,residentKernel=nullptr;\nbool resident=std::getenv("XPU2_RESIDENT_RECORDS") && !std::strcmp(std::getenv("XPU2_RESIDENT_RECORDS"),"1");\nbool residentFlush=xpu2::resident::enabled(std::getenv("XPU2_RESIDENT_FLUSH")),residentStale=xpu2::resident::enabled(std::getenv("XPU2_RESIDENT_STALE"));\nbool fastRecords=!std::getenv("XPU2_RESIDENT_FAST") || xpu2::resident::enabled(std::getenv("XPU2_RESIDENT_FAST"));\nbool injectMixed=xpu2::resident::enabled(std::getenv("XPU2_RESIDENT_MIXED_ONCE")),mixedInjected=false;\nunsigned long long residentRejected=0,residentBatchRejected=0,fastPackets=0,fastBatches=0;\nunsigned long long residentFallback=0;')
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
 # Admission is local: invalid versions never enter the driver-failure path.
 s=once(s,'\n    ++batches;samples+=count;','''
    if(views && (count%8 || !xpu2::resident::Cache::valid(views,unsigned(count)/8))){++residentBatchRejected;return false;}
    ++batches;samples+=count;''')
 s=once(s,'    ++errors;flightBroken=true;','    ++errors;flightBroken=true;\n    for(auto& slot:slots)slot.residentCache.complete(false);')
 s=once(s,'        s.busy=false;','        s.residentCache.complete(false);\n        s.busy=false;')
 s=once(s,'        std::memcpy(s.input(),input,count*96);\n        const bool residentBatch=resident && views;','''        const bool residentBatch=resident && views;
        s.descriptorOnly=residentBatch && fastRecords && leanWire && !records;
        if(!s.descriptorOnly)std::memcpy(s.input(),input,count*96);
        else {++fastBatches;std::copy(views,views+count/8,s.residentViews);}''')
 # Patch only asynchronous completion, not the older synchronous validator.
 begin=s.index('void finishFlight(');end=s.index('\n    void summary()',begin)
 finish=s[begin:end].replace('    if(!failed){','    bool rejectedRecord=false;\n    if(!failed){',1)
 finish=once(finish,'                U native[8]{};','''                U* gpu=result+i*9;
                if(gpu[0]==xpu2::resident::wire::rejected){if(!residentRejected)std::fputs("XPU2: rejected stale/invalid resident record; using native CPU fallback\\n",stderr);++residentRejected;++invalid;rejectedRecord=true;continue;}
                const float* laneInput=s.descriptorOnly?s.residentViews[i/8].group->common+(i%8)*24:input+i*24;
                U native[8]{};''')
 finish=once(finish,'                U* gpu=result+i*9;\n                if(gpu[0]==1)', '                if(gpu[0]==1)')
 finish=finish.replace('std::fwrite(input+i*24,1,96,records)','std::fwrite(laneInput,1,96,records)').replace('std::memcmp(returned+i*24,input+i*24,96)','std::memcmp(returned+i*24,laneInput,96)').replace('input+i*24+1,4','laneInput+1,4').replace('input+i*24+20,4','laneInput+20,4')
 finish=once(finish,'    s.busy=false;++flightCompleted;', '    s.residentCache.complete(!failed && !rejectedRecord);\n    s.busy=false;++flightCompleted;')
 s=s[:begin]+finish+s[end:]
 # Descriptor-only transport retains the existing ownership/cancellation protocol.
 s=once(s,'        bool packed=false;','        bool packed=false,fast=false;\n        xpu2::resident::View views[xpu2::resident::maxPackets];')
 s=once(s,'const float* inputData(){return packed?', 'const float* inputData(){return fast?nullptr:packed?')
 old='                for(auto& r:f.requests)if(r->prepared){r->prepared->expand(r->preparedPacket,r->input);++preparedPool.expanded;}'
 new='''                const bool allPrepared=device.resident && std::all_of(f.requests.begin(),f.requests.end(),[](const Ticket& r){return r->prepared && r->count==8;});
                bool sameOwner=true;std::unique_ptr<xpu2::prepared::Group> mixedRecord;
                if(allPrepared){
                    const auto rev=f.requests.front()->revision;
                    for(unsigned j=0;j<f.requests.size();++j){const auto& r=f.requests[j];f.views[j]={r->prepared.get(),r->prepared->poolSlot,r->preparedPacket};
                        sameOwner=sameOwner && r->owner==ownerToken && r->revision==rev && r->prepared->revision==rev;}
                    if(device.injectMixed && !device.mixedInjected && f.requests.size()>1){
                        mixedRecord=std::make_unique<xpu2::prepared::Group>(*f.views[1].group);++mixedRecord->revision;
                        f.views[1].group=mixedRecord.get();device.mixedInjected=true;}
                }
                const bool validViews=allPrepared && sameOwner && xpu2::resident::Cache::valid(f.views,unsigned(f.requests.size()));
                f.fast=validViews && device.fastRecords && device.leanWire && !device.records;
                if(f.fast)device.fastPackets+=f.requests.size();
                else for(auto& r:f.requests)if(r->prepared){r->prepared->expand(r->preparedPacket,r->input);++preparedPool.expanded;}'''
 s=once(s,old,new)
 s=once(s,'f.token=f.batch->pack(views,unsigned(f.requests.size()),revision);','f.token=f.batch->pack(views,unsigned(f.requests.size()),revision,!f.fast);')
 s=once(s,'std::memcpy(f.input.data()+offset*24,r->input,r->count*96);','if(!f.fast)std::memcpy(f.input.data()+offset*24,r->input,r->count*96);')
 start=s.index('                xpu2::resident::View views[64];')
 end=s.index('\n                xpu2trace::end(11,traceDispatch);',start)
 s=s[:start]+'''                bool started=false;
                if(allPrepared && !sameOwner)++device.residentBatchRejected;
                else started=device.startFlight(i,flights,f.inputData(),f.count,allPrepared?f.views:nullptr);'''+s[end:]
 p.write_text(s)
 p=out/'batch_transport.h';s=p.read_text()
 s=once(s,'Token pack(const PacketView* views,unsigned count,uint64_t revision){','Token pack(const PacketView* views,unsigned count,uint64_t revision,bool copyInput=true){')
 s=once(s,'if(!v.input || !v.fallback','if((copyInput && !v.input) || !v.fallback')
 s=once(s,'            std::memcpy(input_.data()+offset*Layout::inputFloats,','            if(copyInput)std::memcpy(input_.data()+offset*Layout::inputFloats,')
 p.write_text(s)
 p=out/'native_gpu_shading.h';s=p.read_text();s=once(s,'    shaderQueue->preparedPool.report();',r'''    if(const char* name=std::getenv("XPU2_RESIDENT_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        uint64_t batches=0,updates=0,reused=0,descriptors=0,bytes=0;
        for(const auto& slot:d.slots){const auto& c=slot.residentCache;batches+=c.batches;updates+=c.updates;reused+=c.reusedGroups;descriptors+=c.descriptors;bytes+=c.bytes;}
        std::fprintf(f,"{\"enabled\":%s,\"flush\":%s,\"stale\":%s,\"batches\":%llu,\"updates\":%llu,\"reused_groups\":%llu,\"descriptors\":%llu,\"upload_bytes\":%llu,\"fallback_batches\":%llu}\n",d.resident?"true":"false",d.residentFlush?"true":"false",d.residentStale?"true":"false",(unsigned long long)batches,(unsigned long long)updates,(unsigned long long)reused,(unsigned long long)descriptors,(unsigned long long)bytes,d.residentFallback);std::fclose(f);
    }
    if(const char* name=std::getenv("XPU2_RESIDENT_DETAIL_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        uint64_t committed=0,aborted=0,pending=0;
        for(const auto& slot:d.slots){committed+=slot.residentCache.committed;aborted+=slot.residentCache.aborted;pending+=slot.residentCache.pending;}
        std::fprintf(f,"{\"rejected_records\":%llu,\"rejected_batches\":%llu,\"committed\":%llu,\"aborted\":%llu,\"pending\":%llu,\"fast_packets\":%llu,\"fast_batches\":%llu,\"mixed_injected\":%s}\n",d.residentRejected,d.residentBatchRejected,(unsigned long long)committed,(unsigned long long)aborted,(unsigned long long)pending,d.fastPackets,d.fastBatches,d.mixedInjected?"true":"false");std::fclose(f);
    }
    shaderQueue->preparedPool.report();''');p.write_text(s)
