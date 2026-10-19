namespace xpu2::nativepath {
inline void ownedReset(){
    const char* mode=std::getenv("XPU2_OWNED_CHUNKS");ownedDepth=mode && !std::strcmp(mode,"2")?2:0;
    ownedPrepared=0;ownedResumed=0;ownedFinished=0;ownedCanceled=0;
}
inline void ownedFinish(){
    if(ownedPrepared!=ownedFinished+ownedCanceled)throw std::logic_error("Owned chunks survived frame");
    if(const char* name=std::getenv("XPU2_OWNED_PROFILE"))if(FILE* f=std::fopen(name,"a")){
        std::fprintf(f,"{\"depth\":%u,\"prepared\":%llu,\"resumed\":%llu,\"finished\":%llu,\"canceled\":%llu}\n",ownedDepth,
        (unsigned long long)ownedPrepared.load(),(unsigned long long)ownedResumed.load(),(unsigned long long)ownedFinished.load(),(unsigned long long)ownedCanceled.load());std::fclose(f);
    }
}
}
extern "C" unsigned CPP_gpuOwnedChunks(void* raw){
    using namespace xpu2::nativepath;auto* tls=static_cast<moonray::pbr::TLState*>(raw);
    return !currentWindow && !ownedBound && windowSize==8 && CPP_gpuEarlyEnabled(tls) && !tls->isCanceled()?ownedDepth:0;
}
extern "C" bool CPP_gpuOwnedWindowBound(){return xpu2::nativepath::ownedBound;}
extern "C" void CPP_gpuOwnedWindowDetach(uint64_t handle){
    using namespace xpu2::nativepath;auto* p=reinterpret_cast<WindowScope*>(handle);
    if(!p || p!=currentWindow || p->record || p->replay || p->ownerThread!=std::this_thread::get_id())throw std::logic_error("Invalid owned chunk detach");
    p->owned=true;++ownedPrepared;currentWindow=nullptr;
}
extern "C" void CPP_gpuOwnedWindowBind(uint64_t handle){
    using namespace xpu2::nativepath;auto* p=reinterpret_cast<WindowScope*>(handle);
    if(!p || currentWindow || ownedBound || !p->owned || p->revision!=epoch || p->ownerThread!=std::this_thread::get_id())throw std::logic_error("Invalid owned chunk bind");
    currentWindow=p;ownedBound=true;
}
extern "C" void CPP_gpuOwnedWindowCancel(uint64_t handle){
    using namespace xpu2::nativepath;auto* p=reinterpret_cast<WindowScope*>(handle);
    if(!p || !p->owned || p->ownerThread!=std::this_thread::get_id() || (currentWindow && currentWindow!=p))std::terminate();
    if(currentWindow==p){currentWindow=nullptr;ownedBound=false;}
    for(auto& b:p->blocks)clearBlock(b);
    delete p;--windowActive;++ownedCanceled;
}
