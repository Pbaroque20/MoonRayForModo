// Reuse only immutable numeric lobe fields; samples and full replay checks remain.
namespace xpu2::nativepath {
inline bool reusePacking=false,groupReplay=false;
inline std::atomic<uint64_t> preparationCalls{0},replayGroups{0},replayPackets{0};
inline void preparationReset(){
    auto flag=[](const char* n){const char* p=std::getenv(n);return p && !std::strcmp(p,"1");};
    reusePacking=flag("XPU2_REUSE_PACKING");groupReplay=flag("XPU2_GROUP_REPLAY");
    preparationCalls=0;replayGroups=0;replayPackets=0;
}
inline void preparationFinish(){
    if(const char* name=std::getenv("XPU2_PREPARATION_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        std::fprintf(f,"{\"reuse_packing\":%s,\"group_replay\":%s,\"prepared_lobes\":%llu,\"replay_groups\":%llu,\"replay_packets\":%llu}\n",
            reusePacking?"true":"false",groupReplay?"true":"false",
            (unsigned long long)preparationCalls.load(),(unsigned long long)replayGroups.load(),(unsigned long long)replayPackets.load());std::fclose(f);
    }
}
}
extern "C" bool CPP_gpuReusePacking(){using namespace xpu2::nativepath;if(reusePacking)++preparationCalls;return reusePacking;}
extern "C" void CPP_gpuEarlySubmitGroup(const float* input,const uint32_t* pixels,unsigned count,uint64_t* tokens){
    using namespace xpu2::nativepath;
    if(count<1 || count>16)throw std::invalid_argument("Invalid preparation packet group");
    if(!groupReplay || !currentWindow || !currentWindow->replay){CPP_gpuEarlySubmitGroupWindow(input,pixels,count,tokens);return;}
    if(currentWindow->revision!=epoch)throw std::logic_error("Stale replay group");
    // Only the owner thread accesses the block. Compare outside the queue lock.
    WindowPacket* matches[16]={};auto& block=*currentWindow->replay;
    for(unsigned i=0;i<count;++i){
        tokens[i]=0;
        if(block.cursor>=block.packets.size())continue;
        auto& packet=block.packets[block.cursor++];
        if(windowMismatch || std::memcmp(packet.input,input+i*192,sizeof(packet.input)) || std::memcmp(packet.pixels,pixels+i*8,sizeof(packet.pixels))){++windowChanged;discardPacket(packet);}
        else if(windowDrop)discardPacket(packet);
        else if(packet.owner)matches[i]=&packet;
    }
    // Protect done-state reads with one lock; never submit/cancel under this lock.
    {std::lock_guard<std::mutex> lock(shaderQueue->mutex);
        ++replayGroups;
        for(unsigned i=0;i<count;++i)if(auto p=matches[i]){
            if((*p->owner)->done)++windowReady;
            ++windowReused;++replayPackets;tokens[i]=reinterpret_cast<uint64_t>(p->owner.release());
        }
    }
    for(unsigned i=0;i<count;++i)if(!tokens[i])tokens[i]=CPP_gpuEarlySubmitRaw(input+i*192,pixels+i*8);
}
