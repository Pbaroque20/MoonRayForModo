// Diagnostic exclusive wall time per host thread. Never sum threads into frame time.
#pragma once
#include <array>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <mutex>
#include <vector>
#include <string>
#include <algorithm>
#include <thread>
#if defined(__x86_64__) || defined(__i386__)
#include <x86intrin.h>
#include <cpuid.h>
#endif
namespace xpu2cost {
enum Stage {Packing,Upload,Launch,Completion,Readback,Validation,Fallback,Native,Coordination,Context,Wait,Setup,Instrumentation,Count};
inline const char* names[]={"packing","upload_api","launch_api","completion_api","readback_api","replay_validation","rejected_fallback","native_shading","coordination","cuda_context","wait","setup_cleanup","profiler_gpu_queries"};
struct Stats {
 std::array<uint64_t,Count> ns{},calls{};std::array<unsigned,64> stack{};
 std::array<std::array<double,3>,4> gpuMs{};std::array<uint64_t,4> gpuTrips{};
 uint64_t last=0,root=0,covered=0,errors=0;unsigned depth=0;
 void enter(unsigned stage,uint64_t now){
  if(stage>=Count || depth==stack.size() || (depth && now<last)){++errors;return;}
  if(depth)ns[stack[depth-1]]+=now-last;else root=now;
  stack[depth++]=stage;++calls[stage];last=now;
 }
 void leave(uint64_t now){
  if(!depth || now<last){++errors;return;}
  ns[stack[depth-1]]+=now-last;--depth;last=now;
  if(!depth)covered+=now-root;
 }
};
inline bool enabled=false;inline uint64_t generation=0,origin=0;
inline std::mutex registry;inline std::vector<std::unique_ptr<Stats>> buffers;
// Invariant TSC avoids millions of expensive OS clock calls in this diagnostic.
// Only elapsed intervals on one thread are used; no cross-core timestamp ordering.
inline bool fastClock=false;inline double nsPerTick=1;inline uint64_t steadyOrigin=0;
inline uint64_t steady(){return uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count());}
inline uint64_t ticks(){
#if defined(__x86_64__) || defined(__i386__)
 unsigned aux;_mm_lfence();auto t=__rdtscp(&aux);_mm_lfence();return t;
#else
 return steady();
#endif
}
inline void prepareClock(){
 fastClock=false;nsPerTick=1;
#if defined(__x86_64__) || defined(__i386__)
 unsigned a,b,c,d;bool supported=__get_cpuid(0x80000001,&a,&b,&c,&d) && (d&(1u<<27));
 supported=supported && __get_cpuid(0x80000007,&a,&b,&c,&d) && (d&(1u<<8));
 if(supported){
  double ratios[3];
  for(auto& r:ratios){auto n=steady(),t=ticks();std::this_thread::sleep_for(std::chrono::milliseconds(20));auto dt=ticks()-t;auto dn=steady()-n;r=double(dn)/double(dt);}
  std::sort(ratios,ratios+3);
  if(ratios[0]>0 && ratios[2]/ratios[0]<1.001){nsPerTick=ratios[1];fastClock=true;}
 }
#endif
}
inline uint64_t clock(){return fastClock?ticks():steady();}
inline uint64_t nanos(uint64_t value){return uint64_t(double(value)*nsPerTick+.5);}

inline Stats& local(){
 thread_local uint64_t seen=0;thread_local Stats* ptr=nullptr;
 if(seen!=generation){std::lock_guard<std::mutex> lock(registry);buffers.push_back(std::make_unique<Stats>());ptr=buffers.back().get();seen=generation;}
 return *ptr;
}
inline uint64_t begin(unsigned stage){if(!enabled)return 0;auto& s=local();auto n=clock();s.enter(stage,n);return s.depth;}
inline void end(uint64_t token){if(!token)return;auto& s=local();if(token!=s.depth){++s.errors;return;}s.leave(clock());}
struct Scope {uint64_t token;explicit Scope(unsigned stage):token(begin(stage)){}~Scope(){end(token);}Scope(const Scope&)=delete;};
inline void gpu(unsigned track,float upload,float kernel,float readback){if(!enabled)return;auto& s=local();if(track>=4 || upload<0 || kernel<0 || readback<0){++s.errors;return;}s.gpuMs[track][0]+=upload;s.gpuMs[track][1]+=kernel;s.gpuMs[track][2]+=readback;++s.gpuTrips[track];}
inline void reset(){buffers.clear();++generation;enabled=std::getenv("XPU2_EXCLUSIVE_PROFILE")!=nullptr;if(enabled)prepareClock();steadyOrigin=steady();origin=clock();}
inline void finish(){
 if(!enabled)return;const uint64_t duration=nanos(clock()-origin),steadyDuration=steady()-steadyOrigin;const char* path=std::getenv("XPU2_EXCLUSIVE_PROFILE");
 if(FILE* f=std::fopen(path,"w")){
  std::fprintf(f,"thread,stage,exclusive_ns,calls,covered_ns,depth,errors,frame_ns\n");
  for(unsigned t=0;t<buffers.size();++t){const auto& s=*buffers[t];for(unsigned p=0;p<Count;++p)
   std::fprintf(f,"%u,%s,%llu,%llu,%llu,%u,%llu,%llu\n",t,names[p],(unsigned long long)nanos(s.ns[p]),(unsigned long long)s.calls[p],(unsigned long long)nanos(s.covered),s.depth,(unsigned long long)s.errors,(unsigned long long)duration);}
  std::fclose(f);
 }
 std::string gpuPath=std::string(path)+".gpu.csv";
 if(FILE* f=std::fopen(gpuPath.c_str(),"w")){std::fprintf(f,"thread,track,upload_ms,kernel_ms,readback_ms,trips\n");for(unsigned t=0;t<buffers.size();++t)for(unsigned k=0;k<4;++k){const auto& s=*buffers[t];std::fprintf(f,"%u,%u,%.9f,%.9f,%.9f,%llu\n",t,k,s.gpuMs[k][0],s.gpuMs[k][1],s.gpuMs[k][2],(unsigned long long)s.gpuTrips[k]);}std::fclose(f);}
 std::string clockPath=std::string(path)+".clock.csv";
 if(FILE* f=std::fopen(clockPath.c_str(),"w")){std::fprintf(f,"clock,ns_per_tick,frame_ns,steady_frame_ns\n%s,%.12f,%llu,%llu\n",fastClock?"invariant_tsc":"steady",nsPerTick,(unsigned long long)duration,(unsigned long long)steadyDuration);std::fclose(f);}
 enabled=false;
}
}
#define XPU2_COST_CALL(stage,expr) ([&](){xpu2cost::Scope cost(xpu2cost::stage);return (expr);}())
