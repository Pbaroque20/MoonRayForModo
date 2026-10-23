// Private asynchronous complete-sample pipeline, planar fixture domain only.
#pragma once
#include "gpu_lane.h"
#include "cpu_pool.h"
#include <chrono>
namespace xpu2::interactive::mixed {
enum class Owner {Cpu,Gpu};enum class Commit {Ok,Stale,Replay,Invalid};
struct Task {Job job;Owner owner;bool started=false,done=false;};
struct Ledger {
 path::Epoch epoch;std::vector<Task> tasks;std::vector<Pixel> film;
 explicit Ledger(const cpu::PlanView& p):epoch(config(p).epoch),film(p->width*p->height){}
 Commit accept(size_t index,const Result& r,Owner owner,path::Epoch current){
  if(!path::equal(current,epoch))return Commit::Stale;
  if(index>=tasks.size())return Commit::Invalid;auto& t=tasks[index];auto& j=t.job;
  if(!t.started||t.owner!=owner||r.sequence!=j.sequence||!path::equal(r.epoch,epoch)||r.count!=j.count)return Commit::Invalid;
  if(t.done)return Commit::Replay;
  // Validate the whole packet before publishing any of its pixels.
  for(unsigned i=0;i<j.count;++i){auto& p=r.pixels[i];if(p.pixel!=j.pixels[i]||p.pixel>=film.size()||p.status||p.count!=j.samples||film[p.pixel].count)return Commit::Invalid;for(double x:p.sum)if(!std::isfinite(x))return Commit::Invalid;}
  for(unsigned i=0;i<j.count;++i)film[r.pixels[i].pixel]=r.pixels[i];t.done=true;return Commit::Ok;
 }
 std::vector<float> image()const{for(auto& t:tasks)cpu::need(t.done,"Incomplete film");std::vector<float> values;values.reserve(film.size()*4);for(auto& p:film){cpu::need(p.count,"Unsampled pixel");for(auto c:p.sum)values.push_back(float(c/p.count));}return values;}
};
struct Run {
 std::vector<float> rgba;std::vector<Pixel> raw;unsigned first=0,samples=0;bool cpuTextureRoute=false;uint64_t cpuSamples=0,gpuSamples=0,cpuWhileGpuPending=0,started=0,invalidated=0;
 uint64_t windows=0,pendingPaths=0,textureMisses=0,migratedPaths=0,fineRefills=0,gpuTextureRetries=0;unsigned maxFlights=0,refused=0;bool cancelled=false,failed=false,replayRejected=false,staleRejected=false;
};
// 8x8 TEST cells expose CPU/GPU boundaries on the tiny fixture; production's
// default 64x64 cells and cellular work stealing are not implemented here.
inline Run render(cpu::PlanView plan,cpu::AccelView accel,gpu::Lane& lane,gpu::SceneView scene,unsigned threads,int mode,uint64_t ticket,unsigned fault=0,bool cancelAfterLaunch=false,uint64_t delay=0,const std::atomic<uint64_t>* generation=nullptr,const std::atomic<bool>* closing=nullptr,std::atomic<uint64_t>* submitted=nullptr,unsigned first=0,unsigned samples=0,uint64_t submittedBase=0,CpuPool* retainedPool=nullptr){
 cpu::need(threads>0&&threads<=12&&mode>=0&&mode<=2&&ticket<(1ull<<32),"Invalid pipeline request");
 cpu::need(plan&&accel&&scene&&scene->plan==plan&&accel->data.size()==plan->meshes.size(),"Mismatched native scene");for(size_t i=0;i<accel->data.size();++i)cpu::need(accel->data[i]==plan->meshes[i].data,"Stale native acceleration");
 if(!samples)samples=plan->spp;cpu::need(first<plan->spp&&samples<=plan->spp-first,"Sample range");
 bool textured=!plan->diffuseMaps.empty()||!plan->emissionMaps.empty();if(textured){cpu::need(mode!=1,"GPU textures not qualified");mode=0;}
 Ledger ledger(plan);Job partial[2]{};for(auto& j:partial){j.epoch=ledger.epoch;j.first=first;j.samples=samples;j.delay=delay;}
 auto flush=[&](unsigned owner){auto& j=partial[owner];if(!j.count)return;cpu::need(ledger.tasks.size()<65535,"Job identity budget");j.sequence=(ticket<<32)+(uint64_t(first)<<16)+ledger.tasks.size()+1;ledger.tasks.push_back({j,owner?Owner::Gpu:Owner::Cpu});j.count=0;};
 for(unsigned y=0;y<plan->height;y+=8)for(unsigned x=0;x<plan->width;x+=8){unsigned owner=mode==0?0:mode==1?1:((x/8+y/8)&1);auto& j=partial[owner];for(unsigned dy=0;dy<8&&y+dy<plan->height;++dy)for(unsigned dx=0;dx<8&&x+dx<plan->width;++dx){j.pixels[j.count++]=(y+dy)*plan->width+x+dx;if(j.count==Capacity)flush(owner);}}
 flush(0);flush(1);if(fault)for(auto& t:ledger.tasks)if(t.owner==Owner::Gpu){t.job.fault=fault;break;}
 std::unique_ptr<CpuPool> localPool;if(!retainedPool){localPool=std::make_unique<CpuPool>();retainedPool=localPool.get();}auto& pool=*retainedPool;CpuPass cpuPass(pool,mode==1?0:threads);
 std::array<int,4> gpuTasks;gpuTasks.fill(-1);std::map<uint64_t,size_t> cpuTasks;Run run;run.first=first;run.samples=samples;run.cpuTextureRoute=textured;size_t completed=0;bool invalid=false;
 auto beforeDevice=lane.driver.deviceBytes,beforePinned=lane.driver.pinnedBytes;unsigned syncs=lane.driver.synchronizations;auto allocations=lane.driver.allocations,frees=lane.driver.frees;
 auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(120);
 auto commit=[&](size_t i,const Result& r,Owner owner){++completed;auto& t=ledger.tasks[i];uint64_t samples=uint64_t(t.job.count)*t.job.samples;
  if(owner==Owner::Cpu){run.cpuSamples+=samples;if(lane.busy())run.cpuWhileGpuPending+=samples;}else run.gpuSamples+=samples;
  if(invalid)return;auto status=ledger.accept(i,r,owner,ledger.epoch);if(status!=Commit::Ok){invalid=run.failed=true;return;}
  if(!run.replayRejected){run.replayRejected=ledger.accept(i,r,owner,ledger.epoch)==Commit::Replay;auto stale=ledger.epoch;++stale.settings;run.staleRejected=ledger.accept(i,r,owner,stale)==Commit::Stale;}
 };
 for(;;){
  if(std::chrono::steady_clock::now()>deadline)throw std::runtime_error("Mixed pipeline timeout");
  if((generation&&generation->load(std::memory_order_acquire)!=ticket)||(closing&&closing->load(std::memory_order_acquire)))invalid=run.cancelled=true;
  if(!invalid){for(size_t i=0;i<ledger.tasks.size();++i){auto& t=ledger.tasks[i];if(t.started)continue;
    if(t.owner==Owner::Gpu){int slot=lane.submit(scene,t.job);if(slot<0){++run.refused;continue;}gpuTasks[slot]=int(i);t.started=true;}
    else{if(pool.submit(plan,accel,t.job)){t.started=true;cpuTasks[t.job.sequence]=i;}}
    if(t.started){run.started+=uint64_t(t.job.count)*t.job.samples;if(submitted)submitted->store(submittedBase+run.started,std::memory_order_release);}
   }
   run.maxFlights=std::max(run.maxFlights,lane.busy());if(cancelAfterLaunch&&lane.busy()){invalid=run.cancelled=true;}
  }
  for(unsigned n=0;n<threads;++n){Result r;if(!pool.poll(r))break;auto it=cpuTasks.find(r.sequence);cpu::need(it!=cpuTasks.end(),"CPU completion ownership");auto index=it->second;cpuTasks.erase(it);commit(index,r,Owner::Cpu);}
  for(unsigned slot=0;slot<4;++slot)if(gpuTasks[slot]>=0){Result r;if(lane.poll(slot,r)){int index=gpuTasks[slot];gpuTasks[slot]=-1;commit(size_t(index),r,Owner::Gpu);}}
  if(invalid){if(!lane.busy()&&cpuTasks.empty())break;}else if(completed==ledger.tasks.size())break;
  std::this_thread::yield();
 }
 cpu::need(lane.driver.allocations==allocations&&lane.driver.frees==frees,"Per-trip allocation/free calls");
 cpu::need(lane.driver.synchronizations==syncs,"Steady-state CUDA synchronization");cpu::need(lane.driver.deviceBytes==beforeDevice&&lane.driver.pinnedBytes==beforePinned,"Per-trip GPU allocation/free");
 cpuPass.finish();if(invalid){run.invalidated=run.started;return run;}cpu::need(run.cpuSamples+run.gpuSamples==uint64_t(plan->width)*plan->height*samples,"Sample audit mismatch");run.rgba=ledger.image();run.raw=std::move(ledger.film);return run;
}
}
