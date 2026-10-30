"""Publish bounded native lobe packets together; no cross-path migration or timer."""
from pathlib import Path
from . import native_flight as flight
from .native_gpu_paths import once
HERE=Path(__file__).resolve().parent
adapter=flight.adapter
cpp=flight.cpp
profile=flight.profile

def queue(text):
    text=flight.queue(text)
    text=once(text,'    Queue() {','''    bool grouped=std::getenv("XPU2_GROUP_PACKETS") && !std::strcmp(std::getenv("XPU2_GROUP_PACKETS"),"1");
    Queue() {''')
    anchor='''        if(count<1 || count>8)return {};
        std::lock_guard<std::mutex> lock(mutex);
        const auto id=next++;'''
    replacement='''        std::lock_guard<std::mutex> lock(mutex);
        return submitLocked(input,native,count,revision,std::move(resources),pixels);
    }
    // A group contains at most sixteen already-prepared native sample packets.
    // One bounded lock publishes the whole group before the consumer can claim it.
    void submitGroup(const float* input,const float* native,const uint32_t* pixels,
                     unsigned count,uint64_t revision,Ticket* tickets) {
        if(count<1 || count>16)throw std::invalid_argument("Invalid packet group");
        std::lock_guard<std::mutex> lock(mutex);
        unsigned inserted=0;
        try {
            for(;inserted<count;++inserted)
                tickets[inserted]=submitLocked(input+inserted*192,native,8,revision,{},pixels+inserted*8,false);
        } catch(...) {
            // Allocation failure cannot strand published tickets without a caller.
            for(unsigned i=0;i<inserted;++i)if(tickets[i])cancelLocked(tickets[i]);
            throw;
        }
        available.notify_one();
    }
    Ticket submitLocked(const float* input,const float* native,int count,uint64_t revision,
                        std::shared_ptr<const void> resources,const uint32_t* pixels,bool notify=true) {
        if(count<1 || count>8)return {};
        const auto id=next++;'''
    text=once(text,anchor,replacement)
    return once(text,'maxQueue=std::max(maxQueue,(unsigned long long)pending.size());available.notify_one();\n        snapshot();return request;',
        'maxQueue=std::max(maxQueue,(unsigned long long)pending.size());if(notify)available.notify_one();\n        snapshot();return request;')

def header(text):
    text=flight.header(text)
    addition='''extern "C" bool CPP_gpuEarlyGrouped(){return xpu2::nativepath::shaderQueue->grouped;}
extern "C" void CPP_gpuEarlySubmitGroup(const float* input,const uint32_t* pixels,unsigned count,uint64_t* tokens){
    using namespace xpu2::nativepath;
    if(count<1 || count>16)throw std::invalid_argument("Invalid early packet group");
    float empty[64];std::fill(empty,empty+64,std::numeric_limits<float>::quiet_NaN());
    // Allocate caller handles before queue publication, so later allocation cannot
    // lose ownership of a submitted request.
    std::unique_ptr<Queue::Ticket> owners[16];Queue::Ticket tickets[16];
    for(unsigned i=0;i<count;++i)owners[i]=std::make_unique<Queue::Ticket>();
    shaderQueue->submitGroup(input,empty,pixels,count,epoch,tickets);
    for(unsigned i=0;i<count;++i){
        tokens[i]=0;
        if(tickets[i]){*owners[i]=std::move(tickets[i]);tokens[i]=reinterpret_cast<uint64_t>(owners[i].release());++earlySubmitted;}
    }
}
'''
    return once(text,'extern "C" void CPP_gpuEarlyCollect',addition+'extern "C" void CPP_gpuEarlyCollect')

def ispc(text,bsdf_header):
    text=flight.ispc(text,bsdf_header)
    anchor='extern "C" uniform uint64 CPP_gpuEarlySubmit('
    text=once(text,anchor,'''extern "C" uniform bool CPP_gpuEarlyGrouped();
extern "C" void CPP_gpuEarlySubmitGroup(const uniform float *uniform input,const uniform uint32 *uniform pixels,uniform unsigned int count,uniform uint64 *uniform tokens);
'''+anchor)
    text=once(text,'            xpu2Prepared=true;', '''            xpu2Prepared=true;
            uniform bool xpu2Grouped=CPP_gpuEarlyGrouped();
            uniform float xpu2GroupInput[16*192];
            uniform uint32 xpu2GroupPixels[16*8];''')
    text=once(text,'                uniform uint32 xpu2Pixels[8];','                uniform uint32 *uniform xpu2Pixels=&xpu2GroupPixels[j*8];')
    text=once(text,'                uniform float xpu2Input[192];','                uniform float *uniform xpu2Input=&xpu2GroupInput[j*192];')
    return once(text,'''                xpu2Tokens[j]=CPP_gpuEarlySubmit(xpu2Input,xpu2Pixels);
            }
        }''','''                if(!xpu2Grouped)xpu2Tokens[j]=CPP_gpuEarlySubmit(xpu2Input,xpu2Pixels);
            }
            if(xpu2Grouped)CPP_gpuEarlySubmitGroup(xpu2GroupInput,xpu2GroupPixels,reduce_max(lobeSampleCount),xpu2Tokens);
        }''')
