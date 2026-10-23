// Private complete-sample progressive passes. No deadline sample dropping.
#pragma once
#include "mixed_pipeline.h"
namespace xpu2::interactive::mixed {
template<class Publish>inline Run progressive(cpu::PlanView plan,cpu::AccelView accel,gpu::Lane& lane,gpu::SceneView scene,unsigned threads,int mode,uint64_t ticket,unsigned batch,Publish publish,unsigned fault=0,uint64_t delay=0,const std::atomic<uint64_t>* generation=nullptr,const std::atomic<bool>* closing=nullptr,std::atomic<uint64_t>* submitted=nullptr,CpuPool* retainedPool=nullptr){
 std::unique_ptr<CpuPool> localPool;if(!retainedPool){localPool=std::make_unique<CpuPool>();retainedPool=localPool.get();}
 cpu::need(batch>0&&batch<=plan->spp,"Invalid progressive batch");Run total;total.raw.resize(size_t(plan->width)*plan->height);total.rgba.resize(total.raw.size()*4);
 for(unsigned first=0;first<plan->spp;first+=batch){
  auto next=render(plan,accel,lane,scene,threads,mode,ticket,fault==3?(first?1:0):fault,false,delay,generation,closing,submitted,first,std::min(batch,plan->spp-first),total.started,retainedPool);
  if(next.failed||next.cancelled){
   next.cpuSamples+=total.cpuSamples;next.gpuSamples+=total.gpuSamples;next.cpuWhileGpuPending+=total.cpuWhileGpuPending;
   next.started+=total.started;next.invalidated=next.started;next.samples=total.samples;next.refused+=total.refused;next.maxFlights=std::max(next.maxFlights,total.maxFlights);
   next.rgba.clear();next.raw.clear();return next;
  }
  cpu::need(next.first==total.samples&&next.raw.size()==total.raw.size(),"Noncontiguous progressive pass");
  for(size_t i=0;i<total.raw.size();++i){auto& p=total.raw[i];auto& q=next.raw[i];cpu::need(q.count==next.samples&&q.pixel==i&&p.count==first,"Progressive count mismatch");p.pixel=unsigned(i);p.count+=q.count;for(unsigned c=0;c<4;++c){p.sum[c]+=q.sum[c];total.rgba[i*4+c]=float(p.sum[c]/p.count);}}
  total.samples+=next.samples;total.cpuSamples+=next.cpuSamples;total.gpuSamples+=next.gpuSamples;total.started+=next.started;total.cpuWhileGpuPending+=next.cpuWhileGpuPending;total.maxFlights=std::max(total.maxFlights,next.maxFlights);total.refused+=next.refused;total.cpuTextureRoute=next.cpuTextureRoute;
  if((generation&&generation->load(std::memory_order_acquire)!=ticket)||(closing&&closing->load(std::memory_order_acquire))){total.cancelled=true;total.invalidated=total.started;total.raw.clear();total.rgba.clear();return total;}
  if(total.samples<plan->spp)publish(total);
 }
 return total;
}
}
