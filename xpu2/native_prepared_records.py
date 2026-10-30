# Prepare immutable lobe records before window/queue publication; preserve GPU ABI.
from .native_gpu_paths import once

def patch(out):
 import shutil
 from pathlib import Path
 shutil.copyfile(Path(__file__).with_name('prepared_records.h'),out/'prepared_records.h')
 p=out/'early_queue.inc';s=p.read_text();s='#include "prepared_records.h"\n'+s
 s=once(s,'    float input[8*24],output[8*8];','    float input[8*24],output[8*8];\n    std::shared_ptr<const xpu2::prepared::Group> prepared;unsigned preparedPacket=0;')
 s=once(s,'    Bridge device;','    Bridge device;\n    xpu2::prepared::Pool preparedPool;')
 s=once(s,'const uint32_t* pixels,bool notify=true) {','const uint32_t* pixels,bool notify=true,std::shared_ptr<const xpu2::prepared::Group> prepared={},unsigned packet=0) {')
 anchor='        auto request=std::make_shared<Request>();request->id=id;request->count=count;'
 replacement='''        if(prepared && (prepared->revision!=revision || packet>=prepared->count || count!=8 || !flights))throw std::logic_error("Prepared record revision");
        auto request=std::make_shared<Request>();request->id=id;request->count=count;
        request->prepared=std::move(prepared);request->preparedPacket=packet;if(request->prepared)++preparedPool.queued;'''
 assert s.count(anchor)==2;s=s.replace(anchor,replacement,1)
 s=once(s,'        std::memcpy(request->input,input,count*96);std::memcpy(request->output,native,count*32);','        if(!request->prepared)std::memcpy(request->input,input,count*96);std::memcpy(request->output,native,count*32);')
 anchor='                if(f.requests.empty())continue;'
 s=once(s,anchor,anchor+'\n                for(auto& r:f.requests)if(r->prepared){r->prepared->expand(r->preparedPacket,r->input);++preparedPool.expanded;}')
 p.write_text(s)
 p=out/'native_gpu_early.h';s=p.read_text()
 s=once(s,'    float input[192];uint32_t pixels[8];','    float input[192];uint32_t pixels[8];\n    std::shared_ptr<const xpu2::prepared::Group> prepared;unsigned preparedPacket=0;')
 s=once(s,'shaderQueue->submitLocked(p.input,empty,8,epoch,{},p.pixels,false);','shaderQueue->submitLocked(p.input,empty,8,epoch,{},p.pixels,false,p.prepared,p.preparedPacket);')
 s=once(s,'            if(windowMismatch || std::memcmp(p.input,input,sizeof(p.input))', '            float restored[192];const float* expected=p.input;\n            if(p.prepared){p.prepared->expand(p.preparedPacket,restored);expected=restored;}\n            if(windowMismatch || std::memcmp(expected,input,sizeof(p.input))')
 s=once(s,'        for(unsigned lane=0;lane<8;++lane){samples[lane*2]=ticket->input[lane*24+11];samples[lane*2+1]=ticket->input[lane*24+12];}', '        if(ticket->prepared)ticket->prepared->coordinates(ticket->preparedPacket,samples);\n        else for(unsigned lane=0;lane<8;++lane){samples[lane*2]=ticket->input[lane*24+11];samples[lane*2+1]=ticket->input[lane*24+12];}')
 anchor='extern "C" unsigned CPP_gpuIntegrationSubmitPhase()'
 extra=r'''extern "C" bool CPP_gpuPreparedRecordsEnabled(){using namespace xpu2::nativepath;return shaderQueue->preparedPool.enabled && shaderQueue->flights && currentWindow;}
extern "C" void CPP_gpuPreparedSubmit(const float* common,const float* samples,const uint32_t* masks,const uint32_t* pixels,unsigned count,uint64_t* tokens){
    using namespace xpu2::nativepath;
    if(!count||count>16)throw std::invalid_argument("Prepared group size");
    if(recordingWindow()){
        auto group=shaderQueue->preparedPool.acquire(common,samples,masks,pixels,count,epoch);
        if(group){auto& b=*currentWindow->record;if(materialAdmissionMode&&b.packets.empty())b.packets.reserve(32);
            for(unsigned i=0;i<count;++i){tokens[i]=0;if(b.packets.size()>=32){++windowOverflow;continue;}
                b.packets.emplace_back();auto& p=b.packets.back();p.prepared=group;p.preparedPacket=i;
                for(unsigned lane=0;lane<8;++lane)p.pixels[lane]=(masks[i]&(1u<<lane))?pixels[lane]:0xffffffffu;}
            return;
        }
    }
    // Replay and pool exhaustion retain the full original comparison/fallback gate.
    xpu2::prepared::Group group;group.capture(common,samples,masks,pixels,count,epoch);
    for(unsigned i=0;i<count;++i){float input[192];uint32_t ids[8];group.expand(i,input,ids);tokens[i]=CPP_gpuEarlySubmit(input,ids);}
}

'''
 s=once(s,anchor,extra+anchor);p.write_text(s)
 p=out/'native_gpu_shading.h';s=p.read_text();s=once(s,'    shaderQueue.reset();','    shaderQueue->preparedPool.report();\n    if(shaderQueue->preparedPool.retained())throw std::logic_error("Prepared records retained at frame end");\n    shaderQueue.reset();');p.write_text(s)
 p=out/'PathIntegratorUtil.ispc';s=p.read_text();anchor='inline uniform bool xpu2PrepareLobe('
 s=once(s,anchor,'extern "C" uniform bool CPP_gpuPreparedRecordsEnabled();\nextern "C" void CPP_gpuPreparedSubmit(const uniform float *uniform common,const uniform float *uniform samples,const uniform uint32 *uniform masks,const uniform uint32 *uniform pixels,uniform unsigned int count,uniform uint64 *uniform tokens);\n'+anchor)
 start=s.index('            uniform float xpu2GroupInput[16*192];');end=s.index('\n        }\n\n    return xpu2Prepared;',start)
 original=s[start:end]
 lane=original[original.rindex('                    foreach_active(lane){'):]
 lane=lane[:lane.index('\n                    }')+len('\n                    }')]
 lane=lane.replace('xpu2Input[b+11]=extract(xpu2Sample[0],lane);xpu2Input[b+12]=extract(xpu2Sample[1],lane);','')
 prepared='''            if(CPP_gpuPreparedRecordsEnabled()){
                uniform float common[192];uniform uint32 pixels[8],masks[16];uniform float samples[16*16];
                for(uniform int k=0;k<192;++k)common[k]=0.f;
                for(uniform int k=0;k<8;++k)pixels[k]=0xffffffff;
                uniform float *uniform xpu2Input=common;uniform uint32 *uniform xpu2Pixels=pixels;
'''+lane+'''
                for(uniform int j=0;j<reduce_max(lobeSampleCount);++j){
                    masks[j]=0;for(uniform int k=0;k<16;++k)samples[j*16+k]=0.f;
                    if(j<lobeSampleCount){float sample[2];getSample(xpu2Sampler,sample,pv.nonMirrorDepth,*pbrTls->mFs);
                        foreach_active(lane){masks[j]|=1u<<lane;samples[j*16+lane*2]=extract(sample[0],lane);samples[j*16+lane*2+1]=extract(sample[1],lane);}}
                }
                CPP_gpuPreparedSubmit(common,samples,masks,pixels,reduce_max(lobeSampleCount),xpu2Tokens);
            }else{
'''+original+'\n            }'
 s=s[:start]+prepared+s[end:];p.write_text(s)
