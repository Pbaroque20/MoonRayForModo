// Sampled, disjoint CPU operation timing. Diagnostic only; never used for scheduling.
#pragma once
#include "native_exclusive.h"
namespace xpu2cpu {
constexpr unsigned Count=6;
inline const char* names[Count]={"diffuse_sample","other_bsdf_sample","lobe_eval","light_sample_eval","light_tree","material_construct_maps"};
struct Row {uint64_t calls=0,lanes=0,samples=0,sampledLanes=0,ticks=0,rng=1;};
struct Stats {Row rows[Count];unsigned stage=0,active=0;uint64_t errors=0;};
inline std::vector<std::unique_ptr<Stats>> data;
inline std::mutex registry;
inline unsigned rate=0,seed=1;inline uint64_t generation=0,emptyTicks=0;
inline bool enabled=false;
inline void reset(){
 enabled=false;data.clear();++generation;rate=0;seed=1;
 if(const char* v=std::getenv("XPU2_CPU_COST_RATE"))rate=unsigned(std::strtoul(v,nullptr,10));
 if(const char* v=std::getenv("XPU2_CPU_COST_SEED"))seed=unsigned(std::strtoul(v,nullptr,10));
 if(!rate || !std::getenv("XPU2_CPU_COST"))return;
 if(rate>65536)rate=65536;
 xpu2cost::prepareClock();emptyTicks=~uint64_t(0);
 for(unsigned i=0;i<10000;++i){auto t=xpu2cost::clock();auto n=xpu2cost::clock();emptyTicks=std::min(emptyTicks,n-t);}
 enabled=true;
}
inline Stats& local(){
 thread_local uint64_t seen=0;thread_local Stats* ptr=nullptr;
 if(seen!=generation){std::lock_guard<std::mutex> lock(registry);data.push_back(std::make_unique<Stats>());ptr=data.back().get();seen=generation;
  for(unsigned i=0;i<Count;++i)ptr->rows[i].rng=(uint64_t(seed)<<32)^(uint64_t(i+1)*0x9e3779b97f4a7c15ULL)^data.size();}
 return *ptr;
}
inline uint64_t begin(unsigned stage,unsigned lanes){
 if(!enabled || !lanes || stage>=Count)return 0;
 auto& s=local();auto& r=s.rows[stage];++r.calls;r.lanes+=lanes;
 // Pseudorandom inclusion avoids aliasing a regular tile/lobe/sample loop.
 r.rng^=r.rng>>12;r.rng^=r.rng<<25;r.rng^=r.rng>>27;
 if((r.rng*2685821657736338717ULL)%rate)return 0;
 if(s.active){++s.errors;return 0;} // Disjoint call sites, not overlapping scopes.
 s.active=1;s.stage=stage;++r.samples;r.sampledLanes+=lanes;
 return xpu2cost::clock();
}
inline void end(uint64_t token){
 if(!token)return;auto now=xpu2cost::clock();auto& s=local();
 if(!s.active){++s.errors;return;}s.rows[s.stage].ticks+=now-token;s.active=0;
}
inline void finish(){
 if(!enabled)return;enabled=false;
 if(FILE* f=std::fopen(std::getenv("XPU2_CPU_COST"),"w")){
  std::fprintf(f,"thread,stage,calls,lanes,sampled_calls,sampled_lanes,exclusive_ns,errors,active,rate,seed,empty_pair_ns\n");
  for(unsigned t=0;t<data.size();++t){auto& s=*data[t];for(unsigned i=0;i<Count;++i){auto& r=s.rows[i];
   std::fprintf(f,"%u,%s,%llu,%llu,%llu,%llu,%llu,%llu,%u,%u,%u,%llu\n",t,names[i],(unsigned long long)r.calls,(unsigned long long)r.lanes,(unsigned long long)r.samples,(unsigned long long)r.sampledLanes,(unsigned long long)xpu2cost::nanos(r.ticks),(unsigned long long)s.errors,s.active,rate,seed,(unsigned long long)xpu2cost::nanos(emptyTicks));}}
  std::fclose(f);
 }
}
}
extern "C" uint64_t CPP_xpu2CpuCostBegin(unsigned stage,unsigned lanes){return xpu2cpu::begin(stage,lanes);}
extern "C" void CPP_xpu2CpuCostEnd(uint64_t token){xpu2cpu::end(token);}
