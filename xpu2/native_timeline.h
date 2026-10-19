#pragma once
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <mutex>
#include <vector>
namespace xpu2trace {
struct Event { uint64_t begin,end,id;unsigned phase,track; };
struct Buffer { std::vector<Event> events;uint64_t dropped=0; };
inline bool enabled=false;
inline unsigned generation=0;
inline uint64_t origin=0;
inline std::mutex registryMutex;
inline std::vector<std::unique_ptr<Buffer>> buffers;
inline uint64_t raw(){return uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count());}
inline uint64_t now(){return enabled?raw():0;}
inline Buffer& local(){
    thread_local unsigned seen=0;thread_local Buffer* ptr=nullptr;
    if(seen!=generation){std::lock_guard<std::mutex> lock(registryMutex);auto b=std::make_unique<Buffer>();b->events.reserve(16384);ptr=b.get();buffers.push_back(std::move(b));seen=generation;}
    return *ptr;
}
inline void record(unsigned phase,uint64_t begin,uint64_t end,uint64_t id=0,unsigned track=0){
    if(!enabled || !begin)return;
    auto& b=local();if(b.events.size()>=1000000){++b.dropped;return;}
    b.events.push_back({begin,end,id,phase,track});
}
inline void end(unsigned phase,uint64_t begin,uint64_t id=0){record(phase,begin,now(),id);}
struct Scope {unsigned phase;uint64_t begin,id;Scope(unsigned p,uint64_t i=0):phase(p),begin(now()),id(i){}~Scope(){end(phase,begin,id);} };
inline void reset(){buffers.clear();++generation;enabled=std::getenv("XPU2_TIMELINE")!=nullptr;origin=raw();}
inline void finish(){
    if(!enabled)return;
    const uint64_t stopped=raw();const char* file=std::getenv("XPU2_TIMELINE");
    if(FILE* f=std::fopen(file,"w")){
        std::fprintf(f,"thread,phase,begin_ns,end_ns,id,track\n");
        unsigned thread=0;uint64_t dropped=0;
        for(const auto& b:buffers){for(const auto& e:b->events)std::fprintf(f,"%u,%u,%llu,%llu,%llu,%u\n",thread,e.phase,(unsigned long long)(e.begin-origin),(unsigned long long)(e.end-origin),(unsigned long long)e.id,e.track);dropped+=b->dropped;++thread;}
        std::fprintf(f,"0,99,0,%llu,%llu,0\n",(unsigned long long)(stopped-origin),(unsigned long long)dropped);std::fclose(f);
    }
    enabled=false;
}
}
