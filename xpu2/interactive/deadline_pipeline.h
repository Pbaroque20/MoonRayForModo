// Private bounded resumable planar session. Feeder API; never call from Modo.
#pragma once
#include "mixed_pipeline.h"
namespace xpu2::interactive::resume {
using Clock=std::chrono::steady_clock;
struct Audit {uint64_t started=0,completed=0,pending=0,invalidated=0,slices=0,frames=0;unsigned cpuHeld=0,gpuHeld=0,peakCpuHeld=0,peakGpuHeld=0;uint64_t migratedBatches=0,migratedPaths=0,textureMisses=0,fineRefills=0,gpuTextureRetries=0;};
class Session {
 struct Entry {mixed::Job job;mixed::Owner owner;bool assigned=false,running=false,done=false,needsMigration=false,downloading=false,fineRetried=false;uint64_t gpuCommitted=0;unsigned revision=0;int gpu=-1;std::shared_ptr<Batch> batch;mixed::Result last{};};
 cpu::PlanView plan_;cpu::AccelView accel_;gpu::Lane& lane_;gpu::SceneView scene_;mixed::CpuPool& pool_;
 std::thread::id owner_=std::this_thread::get_id();std::vector<Entry> entries_;std::map<uint64_t,size_t> cpuRunning_;
 gpu::SceneView finePending_;
 bool cancelled_=false,failed_=false,finished_=false;unsigned threads_;Audit counters_;
 unsigned hostCap()const{return 2*threads_+(cpu::gpuTextures(plan_->domain)?4u:0u);}
 void owner()const{cpu::need(owner_==std::this_thread::get_id(),"Deadline session requires feeder");}
 void release(Entry& e){if(e.running)return;if(e.gpu>=0){lane_.releaseResume(unsigned(e.gpu));e.gpu=-1;--counters_.gpuHeld;}if(e.batch){e.batch.reset();--counters_.cpuHeld;}}
 void accept(size_t index,const mixed::Result& r){auto& e=entries_.at(index);e.running=false;++counters_.slices;
  bool valid=path::equal(r.epoch,e.job.epoch)&&r.sequence==e.job.sequence&&r.count==e.job.count&&r.pad==e.revision+1;bool done=true,miss=false;
  if(valid)for(unsigned i=0;i<r.count;++i){const auto& p=r.pixels[i];auto old=e.last.pixels[i].count;
   valid&=p.pixel==e.job.pixels[i]&&p.status==0&&p.count>=old&&p.count<=e.job.samples&&(p.pad<=Complete||p.pad==TextureWait)&&(p.pad==Complete)==(p.count==e.job.samples);
   for(double c:p.sum)valid&=std::isfinite(c);done&=p.pad==Complete;miss|=p.pad==TextureWait;
  }
  if(!valid){failed_=cancelled_=true;release(e);return;}
  e.last=r;e.revision=r.pad;e.done=done;e.needsMigration=miss;if(done||cancelled_)release(e);
 }
 void pump(){
  if(finePending_&&finePending_->ready()){scene_=finePending_;lane_.finishFine(scene_);finePending_.reset();}
  for(unsigned n=0;n<24;++n){mixed::Result r;if(!pool_.poll(r))break;auto it=cpuRunning_.find(r.sequence);cpu::need(it!=cpuRunning_.end(),"Unknown continuation completion");auto index=it->second;cpuRunning_.erase(it);accept(index,r);}
  for(size_t i=0;i<entries_.size();++i){auto& e=entries_[i];if(e.running&&e.gpu>=0&&!e.downloading){mixed::Result r;if(lane_.pollResume(unsigned(e.gpu),r))accept(i,r);}}
  for(auto& e:entries_){
   if(!cancelled_&&e.needsMigration&&!e.running&&e.gpu>=0){
    if(scene_->refillFine){if(!finePending_){finePending_=lane_.requestFine(scene_);++counters_.fineRefills;}continue;}
    if(scene_->includeFine&&!e.fineRetried){e.fineRetried=true;e.needsMigration=false;lane_.rebindResume(unsigned(e.gpu),scene_);++counters_.gpuTextureRetries;continue;}
   }
   if(e.downloading){if(!lane_.pollMigration(unsigned(e.gpu),*e.batch))continue;e.running=e.downloading=false;
    if(!validateMigration(*e.batch,e.job,e.last)){failed_=cancelled_=true;release(e);continue;}
    lane_.releaseResume(unsigned(e.gpu));e.gpu=-1;--counters_.gpuHeld;e.owner=mixed::Owner::Cpu;e.needsMigration=false;++counters_.migratedBatches;
    for(unsigned i=0;i<e.job.count;++i){auto& path=e.batch->paths[i];e.gpuCommitted+=path.film.count;if(path.phase!=Complete)++counters_.migratedPaths;if(path.phase==TextureWait){path.phase=Shade;e.last.pixels[i].pad=Shade;++counters_.textureMisses;}}
   }
   if(!cancelled_&&e.needsMigration&&!e.running&&counters_.cpuHeld<hostCap()){cpu::need(e.gpu>=0&&!e.batch,"Missing texture migration owner");e.batch=std::make_shared<Batch>();++counters_.cpuHeld;counters_.peakCpuHeld=std::max(counters_.peakCpuHeld,counters_.cpuHeld);lane_.beginMigration(unsigned(e.gpu));e.running=e.downloading=true;}
  }
  if(cancelled_)for(auto& e:entries_)release(e);
 }
 bool dispatch(Entry& e,size_t index,unsigned steps,Clock::time_point end){
  if(e.running||e.done||e.needsMigration||(finePending_&&e.owner==mixed::Owner::Gpu))return false;
  if(e.owner==mixed::Owner::Cpu){
   if(!e.batch){if(counters_.cpuHeld>=2*threads_)return false;e.batch=std::make_shared<Batch>();initialize(*e.batch,e.job);++counters_.cpuHeld;counters_.peakCpuHeld=std::max(counters_.peakCpuHeld,counters_.cpuHeld);}
   if(!pool_.submit(plan_,accel_,e.job,e.batch,steps,end))return false;cpuRunning_[e.job.sequence]=index;
  }else{
   if(e.gpu<0){if(cpu::gpuTextures(plan_->domain)&&counters_.cpuHeld+counters_.gpuHeld>=hostCap())return false;int slot=lane_.submitResume(scene_,e.job,steps);if(slot<0)return false;e.gpu=slot;++counters_.gpuHeld;counters_.peakGpuHeld=std::max(counters_.peakGpuHeld,counters_.gpuHeld);}
   else {lane_.rebindResume(unsigned(e.gpu),scene_);lane_.resumeLaunch(unsigned(e.gpu),steps,false);}
  }
  e.assigned=e.running=true;return true;
 }
public:
 Session(cpu::PlanView plan,cpu::AccelView accel,gpu::Lane& lane,gpu::SceneView scene,mixed::CpuPool& pool,unsigned threads,int mode,uint64_t ticket,unsigned fault=0):plan_(plan),accel_(accel),lane_(lane),scene_(scene),pool_(pool),threads_(threads){
  cpu::need(plan&&accel&&scene&&scene->plan==plan&&threads>0&&threads<=12&&mode>=0&&mode<=2&&ticket>0&&ticket<(1ull<<32)&&fault<=2,"Invalid deadline session");cpu::need(plan->width*uint64_t(plan->height)<=262144,"Deadline film budget");cpu::need(!lane.busy()&&!lane.held(),"GPU lane already owned");
  cpu::need(accel->data.size()==plan->meshes.size(),"Resume acceleration");for(size_t i=0;i<accel->data.size();++i)cpu::need(accel->data[i]==plan->meshes[i].data,"Stale resume acceleration");
  bool textured=!plan->diffuseMaps.empty()||!plan->emissionMaps.empty();if(textured&&!cpu::gpuTextures(plan->domain)){cpu::need(mode!=1,"GPU textures not qualified");mode=0;}
  mixed::Job pending[2]{};for(auto& j:pending){j.epoch=mixed::config(plan).epoch;j.samples=plan->spp;}
  auto flush=[&](unsigned who){auto& j=pending[who];if(!j.count)return;j.sequence=(ticket<<32)+entries_.size()+1;Entry e{};e.job=j;e.owner=who?mixed::Owner::Gpu:mixed::Owner::Cpu;for(unsigned i=0;i<j.count;++i)e.last.pixels[i].pixel=j.pixels[i];entries_.push_back(std::move(e));j.count=0;};
  for(unsigned y=0;y<plan->height;y+=8)for(unsigned x=0;x<plan->width;x+=8){unsigned who=mode==0?0:mode==1?1:((x/8+y/8)&1);auto& j=pending[who];for(unsigned dy=0;dy<8&&y+dy<plan->height;++dy)for(unsigned dx=0;dx<8&&x+dx<plan->width;++dx){j.pixels[j.count++]=(y+dy)*plan->width+x+dx;if(j.count==mixed::Capacity)flush(who);}}flush(0);flush(1);
  if(fault)for(auto& e:entries_)if(e.owner==mixed::Owner::Gpu){e.job.fault=fault;break;}
  if(scene_->fineReplacement&&scene_->fineReplacement->ready()){scene_=scene_->fineReplacement;lane_.finishFine(scene_);}
  pool_.begin(mode==1&&!cpu::gpuTextures(plan->domain)?0:threads);
 }
 ~Session(){try{cancel();drain();}catch(...){pool_.abandon();}}
 Session(const Session&)=delete;
 // Repeated calls before/after the deadline never wait for a completion. Existing
 // GPU launches may finish later; their slot and scene remain owned until polled.
 void tick(path::Epoch current,Clock::time_point startCutoff,Clock::time_point traceEnd,unsigned steps=32){
  owner();cpu::need(!finished_&&steps>0&&steps<=64&&startCutoff<=traceEnd,"Invalid trace window");
  if(!path::equal(current,mixed::config(plan_).epoch))cancelled_=true;pump();
  if(cancelled_||Clock::now()>=traceEnd)return;
  for(size_t i=0;i<entries_.size();++i){if(Clock::now()>=traceEnd)return;auto& e=entries_[i];if(e.assigned)dispatch(e,i,steps,traceEnd);}
  for(size_t i=0;i<entries_.size();++i){if(Clock::now()>=startCutoff)return;auto& e=entries_[i];if(!e.assigned)dispatch(e,i,steps,traceEnd);}
 }
 void frame(){owner();++counters_.frames;}
 bool busy()const{return !cpuRunning_.empty()||lane_.busy()||(finePending_&&!finePending_->ready());}
 bool done()const{if(cancelled_)return false;for(auto& e:entries_)if(!e.done)return false;return true;}
 bool cancelled()const{return cancelled_;}bool failed()const{return failed_;}
 void cancel(){owner();cancelled_=true;}
 void drain(){owner();if(finished_)return;auto until=Clock::now()+std::chrono::seconds(120);while(busy()){cpu::need(Clock::now()<until,"Continuation drain timeout");pump();std::this_thread::yield();}if(cancelled_)for(auto& e:entries_)release(e);cpu::need(done()||cancelled_,"Cannot discard paused paths");pool_.finish();finished_=true;}
 Audit audit()const{owner();auto a=counters_;for(auto& e:entries_)for(unsigned i=0;i<e.job.count;++i){auto& p=e.last.pixels[i];a.completed+=p.count;a.pending+=active(p.pad)?1:0;}a.started=a.completed+a.pending;if(cancelled_){a.invalidated=a.started;a.started=a.completed=a.pending=0;}return a;}
 std::array<uint64_t,8> phases()const{owner();std::array<uint64_t,8> out{};for(auto& e:entries_)for(unsigned i=0;i<e.job.count;++i)++out.at(e.last.pixels[i].pad);return out;}
 mixed::Run snapshot()const{owner();mixed::Run r;r.cancelled=cancelled_;r.failed=failed_;auto a=audit();r.started=a.started;r.invalidated=a.invalidated;r.windows=a.frames;r.pendingPaths=a.pending;r.textureMisses=a.textureMisses;r.migratedPaths=a.migratedPaths;r.fineRefills=a.fineRefills;r.gpuTextureRetries=a.gpuTextureRetries;if(cancelled_)return r;r.raw.resize(plan_->width*plan_->height);r.rgba.resize(r.raw.size()*4);r.samples=plan_->spp;
  for(auto& e:entries_){r.gpuSamples+=e.gpuCommitted;for(unsigned i=0;i<e.job.count;++i){auto p=e.last.pixels[i];r.raw[p.pixel]=p;for(unsigned c=0;c<4;++c)r.rgba[p.pixel*4+c]=p.count?float(p.sum[c]/p.count):0.f;r.samples=std::min(r.samples,p.count);if(e.owner==mixed::Owner::Cpu)r.cpuSamples+=p.count;else r.gpuSamples+=p.count;}if(e.owner==mixed::Owner::Cpu)r.cpuSamples-=e.gpuCommitted;}
  return r;
 }
};
// Runs on the background feeder. A frame boundary takes a snapshot of completed
// samples and immediately yields the scheduling window; it does not drain paths.
template<class Publish>inline mixed::Run renderWindows(cpu::PlanView plan,cpu::AccelView accel,gpu::Lane& lane,gpu::SceneView scene,mixed::CpuPool& pool,unsigned threads,uint64_t ticket,unsigned windowMs,Publish publish,unsigned fault=0,const std::atomic<uint64_t>* generation=nullptr,const std::atomic<bool>* closing=nullptr,std::atomic<uint64_t>* submitted=nullptr,unsigned publishEveryMs=0){
 cpu::need(windowMs>0&&windowMs<=100,"Trace window budget");Session session(plan,accel,lane,scene,pool,threads,2,ticket,fault);auto epoch=mixed::config(plan).epoch;auto limit=Clock::now()+std::chrono::seconds(120);uint64_t published=0;auto nextPublish=Clock::now();cpu::need(publishEveryMs<=1000,"Publish interval budget");
 while(!session.done()&&!session.cancelled()){
  cpu::need(Clock::now()<limit,"Deadline renderer timeout");session.frame();auto begin=Clock::now();auto end=begin+std::chrono::milliseconds(windowMs);auto cutoff=begin+std::chrono::microseconds(windowMs*800);
  do{
   if((generation&&generation->load(std::memory_order_acquire)!=ticket)||(closing&&closing->load(std::memory_order_acquire)))session.cancel();
   session.tick(epoch,cutoff,end);if(session.done()||session.cancelled())break;std::this_thread::yield();
  }while(Clock::now()<end);
  auto a=session.audit();if(submitted)submitted->store(a.started,std::memory_order_release);
  if(!session.done()&&!session.cancelled()&&a.completed>published&&Clock::now()>=nextPublish){publish(session.snapshot());published=a.completed;nextPublish=Clock::now()+std::chrono::milliseconds(publishEveryMs);}
 }
 session.drain();auto image=session.snapshot();if(submitted)submitted->store(image.cancelled?image.invalidated:image.started,std::memory_order_release);return image;
}
}
