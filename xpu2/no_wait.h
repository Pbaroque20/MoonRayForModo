#pragma once
#include <cstdlib>
#include <cstring>
#include <cstdio>
namespace xpu2::nowait {
inline bool flag(const char* name){const char* p=std::getenv(name);return p && !std::strcmp(p,"1");}
inline bool enabled(){return flag("XPU2_NO_WAIT");}
// Caller holds the queue lock. Active includes reserved/preparing flights.
inline bool admit(unsigned active,unsigned slots,size_t pending,size_t count,unsigned perSlot){
 return slots && active<slots && count<=size_t(slots-active)*perSlot && pending<=size_t(slots-active)*perSlot-count;
}
inline void report(const char* queue,bool enabled,unsigned long long refused,unsigned long long missed,unsigned active,size_t pending,unsigned long long retained){
 if(const char* path=std::getenv("XPU2_NO_WAIT_PROFILE"))if(FILE* f=std::fopen(path,"a")){
  std::fprintf(f,"{\"queue\":\"%s\",\"enabled\":%s,\"busy_refused\":%llu,\"late_cpu\":%llu,\"active\":%u,\"pending\":%llu,\"retained\":%llu}\n",queue,enabled?"true":"false",refused,missed,active,(unsigned long long)pending,retained);std::fclose(f);
 }
}
}
