// Owner-thread, bounded numeric prefetch. No native shader/arena pointer is retained.
namespace xpu2::nativepath {
struct WindowPacket {
    float input[192];uint32_t pixels[8];
    std::unique_ptr<Queue::Ticket> owner;
};
struct WindowBlock {std::vector<WindowPacket> packets;unsigned cursor=0;};
struct WindowScope {
    uint64_t revision=epoch;
    WindowBlock blocks[4];
    WindowBlock* record=nullptr;WindowBlock* replay=nullptr;
    WindowScope(){for(auto& b:blocks)b.packets.reserve(32);}
};
inline thread_local WindowScope* currentWindow=nullptr;
inline unsigned windowSize=0;
inline bool windowMismatch=false,windowDrop=false;
inline std::atomic<uint64_t> windowScopes{0},windowActive{0},windowPublished{0},windowReused{0},windowDiscarded{0},windowChanged{0},windowReady{0},windowWindows{0},windowOverflow{0};
inline void discardPacket(WindowPacket& p){
    if(p.owner){shaderQueue->cancel(*p.owner);p.owner.reset();++windowDiscarded;}
}
inline void clearBlock(WindowBlock& b){for(auto& p:b.packets)discardPacket(p);b.packets.clear();b.cursor=0;}
inline bool recordingWindow(){return currentWindow && currentWindow->record;}
inline void windowReset(){
    if(windowActive)throw std::logic_error("Window scope survived a frame");
    const char* size=std::getenv("XPU2_WINDOW_BLOCKS");windowSize=size?unsigned(std::max(0,std::min(4,std::atoi(size)))):0;
    windowMismatch=std::getenv("XPU2_WINDOW_MISMATCH")!=nullptr;
    windowDrop=std::getenv("XPU2_WINDOW_DROP")!=nullptr;
    windowScopes=0;windowPublished=0;windowReused=0;windowDiscarded=0;windowChanged=0;windowReady=0;windowWindows=0;windowOverflow=0;
}
inline void windowFinish(){
    if(windowActive || windowPublished!=windowReused+windowDiscarded)throw std::logic_error("Unretired material window");
    if(const char* name=std::getenv("XPU2_WINDOW_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        std::fprintf(f,"{\"blocks\":%u,\"scopes\":%llu,\"active\":%llu,\"windows\":%llu,\"published\":%llu,\"reused\":%llu,\"discarded\":%llu,\"changed\":%llu,\"ready_at_replay\":%llu,\"overflow\":%llu}\n",windowSize,
          (unsigned long long)windowScopes.load(),(unsigned long long)windowActive.load(),(unsigned long long)windowWindows.load(),(unsigned long long)windowPublished.load(),(unsigned long long)windowReused.load(),(unsigned long long)windowDiscarded.load(),(unsigned long long)windowChanged.load(),(unsigned long long)windowReady.load(),(unsigned long long)windowOverflow.load());std::fclose(f);
    }
}
}
extern "C" uint64_t CPP_gpuWindowBegin(moonray::pbr::TLState* tls){
    using namespace xpu2::nativepath;
    if(!windowSize || currentWindow || !CPP_gpuEarlyEnabled(tls) || tls->isCanceled())return 0;
    auto scope=std::make_unique<WindowScope>();currentWindow=scope.release();++windowScopes;++windowActive;
    return reinterpret_cast<uint64_t>(currentWindow);
}
extern "C" unsigned CPP_gpuWindowSize(){return xpu2::nativepath::windowSize;}
extern "C" void CPP_gpuWindowEnd(uint64_t handle){
    using namespace xpu2::nativepath;
    if(!handle)return;
    if(reinterpret_cast<WindowScope*>(handle)!=currentWindow)throw std::logic_error("Wrong window owner");
    for(auto& b:currentWindow->blocks)clearBlock(b);
    delete currentWindow;currentWindow=nullptr;--windowActive;
}
extern "C" void CPP_gpuWindowRecord(uint64_t handle,unsigned block){
    using namespace xpu2::nativepath;
    if(!handle)return;
    if(reinterpret_cast<WindowScope*>(handle)!=currentWindow || block>=windowSize || currentWindow->revision!=epoch)throw std::logic_error("Invalid window record");
    if(block==0){for(auto& b:currentWindow->blocks)clearBlock(b);++windowWindows;}
    currentWindow->replay=nullptr;currentWindow->record=&currentWindow->blocks[block];
}
extern "C" void CPP_gpuWindowPublish(uint64_t handle){
    using namespace xpu2::nativepath;
    if(!handle)return;
    if(reinterpret_cast<WindowScope*>(handle)!=currentWindow)throw std::logic_error("Wrong window publication");
    currentWindow->record=nullptr;
    float empty[64];std::fill(empty,empty+64,std::numeric_limits<float>::quiet_NaN());
    // Allocate handles before publication; hold one bounded lock across blocks.
    for(auto& b:currentWindow->blocks)for(auto& p:b.packets)p.owner=std::make_unique<Queue::Ticket>();
    std::lock_guard<std::mutex> lock(shaderQueue->mutex);
    try {
        for(auto& b:currentWindow->blocks)for(auto& p:b.packets){
            *p.owner=shaderQueue->submitLocked(p.input,empty,8,epoch,{},p.pixels,false);
            if(*p.owner){++earlySubmitted;++windowPublished;}else p.owner.reset();
        }
    }catch(...){
        for(auto& b:currentWindow->blocks)for(auto& p:b.packets)if(p.owner){
            if(*p.owner){shaderQueue->cancelLocked(*p.owner);++windowDiscarded;}p.owner.reset();
        }
        throw;
    }
    shaderQueue->available.notify_one();
}
extern "C" void CPP_gpuWindowReplay(uint64_t handle,unsigned block){
    using namespace xpu2::nativepath;
    if(!handle)return;
    if(reinterpret_cast<WindowScope*>(handle)!=currentWindow || block>=windowSize || currentWindow->revision!=epoch)throw std::logic_error("Invalid window replay");
    currentWindow->replay=&currentWindow->blocks[block];
}
extern "C" void CPP_gpuWindowReplayEnd(){
    using namespace xpu2::nativepath;
    if(currentWindow && currentWindow->replay){clearBlock(*currentWindow->replay);currentWindow->replay=nullptr;}
}
extern "C" uint64_t CPP_gpuEarlySubmit(const float* input,const uint32_t* pixels){
    using namespace xpu2::nativepath;
    if(recordingWindow()){
        auto& b=*currentWindow->record;
        if(b.packets.size()>=32){++windowOverflow;return 0;}
        b.packets.emplace_back();auto& p=b.packets.back();
        std::memcpy(p.input,input,sizeof(p.input));std::memcpy(p.pixels,pixels,sizeof(p.pixels));
        return 0;
    }
    if(currentWindow && currentWindow->replay){
        auto& b=*currentWindow->replay;
        if(b.cursor<b.packets.size()){
            auto& p=b.packets[b.cursor++];
            if(windowMismatch || std::memcmp(p.input,input,sizeof(p.input)) || std::memcmp(p.pixels,pixels,sizeof(p.pixels))){++windowChanged;discardPacket(p);}
            else if(windowDrop){discardPacket(p);}
            else if(p.owner){
                {std::lock_guard<std::mutex> lock(shaderQueue->mutex);if((*p.owner)->done)++windowReady;}
                ++windowReused;return reinterpret_cast<uint64_t>(p.owner.release());
            }
        }
    }
    return CPP_gpuEarlySubmitRaw(input,pixels);
}
extern "C" void CPP_gpuEarlySubmitGroup(const float* input,const uint32_t* pixels,unsigned count,uint64_t* tokens){
    using namespace xpu2::nativepath;
    if(count<1 || count>16)throw std::invalid_argument("Invalid window packet group");
    if(currentWindow && (currentWindow->record || currentWindow->replay)){
        for(unsigned i=0;i<count;++i)tokens[i]=CPP_gpuEarlySubmit(input+i*192,pixels+i*8);
    }else CPP_gpuEarlySubmitGroupRaw(input,pixels,count,tokens);
}
