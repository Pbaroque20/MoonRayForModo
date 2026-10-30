// Private mixed CPU/OptiX service. The feeder owns CUDA for its entire lifetime.
// Requests only carry immutable prepared plans; no Modo API or native qualification.
#pragma once
#include "progressive.h"
#include "deadline_pipeline.h"
#include "spsc_ring.h"
#include <condition_variable>
#include <optional>
namespace xpu2::interactive::mixed {
using cpu::Plan;using cpu::PlanView;using cpu::AccelView;using cpu::need;using cpu::acceleration;
struct Request {uint64_t ticket=0;PlanView plan;unsigned threads=0,fault=0;uint64_t delay=0;unsigned passSamples=0,windowMs=0;bool refillFine=false;unsigned publishMs=0;};
struct Packet {
 uint64_t ticket=0;Epoch epoch{};Run image;std::string error;
 // Unqualified native pixels cannot be labelled fidelity tier N.
 char tier='D';bool qualified=false,final=true;
};
using PacketPtr=std::unique_ptr<Packet>;
struct ServiceCounts {uint64_t submitted,coalesced,started,published,cancelled,discarded,failed,reusedAcceleration,gpuStarts,gpuMeshesBuilt,gpuMeshesReused,progressivePublished,progressiveSkipped,cpuWorkersCreated,cpuJobsSubmitted,cpuJobsCollected,cpuPasses,cpuWorkersJoined,cpuJobsDiscarded;unsigned cpuPeakOutstanding,cpuParked;};
class Service {
 const std::string ptx_;const bool prewarm_;
 const std::thread::id owner_=std::this_thread::get_id();
 SpscRing<Request,4> requests_;
 SpscRing<PacketPtr,2> results_;
 // Host returns obsolete packets to the worker for destruction. If this ring
 // is full, poll simply applies backpressure; no large buffer is freed there.
 SpscRing<PacketPtr,4> retired_;PacketPtr held_;
 std::atomic<uint64_t> latest_{0},active_{0},progress_{0},failedTicket_{0};
 std::atomic<bool> closing_{false},closed_{false};
 std::atomic<uint64_t> submitted_{0},coalesced_{0},started_{0},published_{0},cancelled_{0},discarded_{0},failed_{0},reused_{0},gpuStarts_{0},gpuBuilt_{0},gpuReused_{0},partialPublished_{0},partialSkipped_{0};
 std::atomic<uint64_t> cpuCreated_{0},cpuSubmitted_{0},cpuCollected_{0},cpuPasses_{0},cpuJoined_{0},cpuDiscarded_{0};std::atomic<unsigned> cpuPeak_{0},cpuParked_{0};
 std::weak_ptr<const Plan> lastPlan_;std::optional<Epoch> epoch_;
 std::mutex waitMutex_;std::condition_variable wake_;std::thread worker_;
 void owner()const{if(std::this_thread::get_id()!=owner_)throw std::logic_error("Mixed service requires its coordinator");}
 uint64_t next()const {auto n=latest_.load(std::memory_order_relaxed);need(n<(1ull<<32)-1,"Service generation exhausted");return n+1;}
 void idle(){std::unique_lock<std::mutex> lock(waitMutex_);wake_.wait_for(lock,std::chrono::milliseconds(1));}
 void retire(){PacketPtr p;while(retired_.tryPop(p))p.reset();}
 void run()noexcept {
  CpuPool pool;auto poolStats=[&]{auto c=pool.counts();cpuCreated_=c.created;cpuSubmitted_=c.submitted;cpuCollected_=c.collected;cpuPasses_=c.passes;cpuJoined_=c.joined;cpuDiscarded_=c.discarded;cpuPeak_=c.peakOutstanding;cpuParked_=c.parked;};
  AccelView cache;std::unique_ptr<gpu::Lane> lane;gpu::SceneView scene;Request request;PacketPtr packet;
  std::exception_ptr warmFailure;
  // Native opt-in only. Initialize on the feeder while the scene coordinator
  // reads/admit/captures its immutable input. No CUDA context crosses threads.
  if(prewarm_){try{lane=std::make_unique<gpu::Lane>(ptx_);++gpuStarts_;}catch(...){warmFailure=std::current_exception();}}
  try{while(!closing_.load(std::memory_order_acquire)){
   retire();Request incoming;
   while(requests_.tryPop(incoming)){if(request.plan)++coalesced_;request=std::move(incoming);}
   if(!request.plan){poolStats();idle();continue;}
   if(request.ticket!=latest_.load(std::memory_order_acquire)){++discarded_;request=Request{};continue;}
   auto ticket=request.ticket;progress_.store(0);active_.store(ticket,std::memory_order_release);++started_;
   packet=std::make_unique<Packet>();packet->ticket=ticket;packet->epoch=request.plan->source->routing->epoch;
   try{
    if(warmFailure){auto error=warmFailure;warmFailure=nullptr;std::rethrow_exception(error);}
    auto prepared=acceleration(request.plan,cache);if(prepared==cache)++reused_;cache=std::move(prepared);
    if(!lane){lane=std::make_unique<gpu::Lane>(ptx_);++gpuStarts_;}
    if(scene&&scene->fineReplacement&&scene->fineReplacement->ready()){scene=scene->fineReplacement;lane->finishFine(scene);}
    if(!scene||scene->plan!=request.plan||(scene->refillFine||scene->includeFine)!=request.refillFine){
     gpu::TextureOptions textures;if(request.refillFine){textures.texelBudget=64ull<<20;textures.includeFine=scene&&scene->includeFine;textures.refillFine=!textures.includeFine;}
     auto nextScene=lane->prepare(request.plan,scene,textures);
     auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(90);
     while(!nextScene->ready()){need(std::chrono::steady_clock::now()<deadline,"GPU scene preparation timeout");std::this_thread::yield();}
     gpuBuilt_+=nextScene->built;gpuReused_+=nextScene->reused;scene=std::move(nextScene);lane->collect(scene);
    }
    if(request.passSamples||request.windowMs){
     auto publish=[&](const Run& image){
      retire();if(latest_.load(std::memory_order_acquire)!=ticket||closing_.load(std::memory_order_acquire)||results_.full()){++partialSkipped_;return;}
      auto preview=std::make_unique<Packet>();preview->ticket=ticket;preview->epoch=packet->epoch;preview->final=false;preview->image=image;
      if(results_.tryPush(preview)){++partialPublished_;++published_;}else ++partialSkipped_;
     };
     if(request.windowMs)packet->image=resume::renderWindows(request.plan,cache,*lane,scene,pool,request.threads,ticket,request.windowMs,publish,request.fault,&latest_,&closing_,&progress_,request.publishMs);
     else packet->image=progressive(request.plan,cache,*lane,scene,request.threads,2,ticket,request.passSamples,publish,request.fault,request.delay,&latest_,&closing_,&progress_,&pool);
    }else packet->image=render(request.plan,cache,*lane,scene,request.threads,2,ticket,request.fault,false,request.delay,&latest_,&closing_,&progress_,0,0,0,&pool);
    need(!packet->image.failed,"Invalid native completion; entire epoch requires reference fallback");
    if(packet->image.cancelled)++cancelled_;
   }catch(const std::exception& error){failedTicket_.store(ticket,std::memory_order_release);packet->error=error.what();packet->image=Run{};scene.reset();lane.reset();++failed_;}
   catch(...){failedTicket_.store(ticket,std::memory_order_release);packet->error="Unknown native worker failure";packet->image=Run{};scene.reset();lane.reset();++failed_;}
   poolStats();request=Request{};active_.store(0,std::memory_order_release);
   // Hold at most one finished packet while the two output slots are occupied.
   // A new edit or close invalidates it without waiting for the consumer.
   while(packet){
    retire();
    if(closing_.load(std::memory_order_acquire)||ticket!=latest_.load(std::memory_order_acquire)||packet->image.cancelled){packet.reset();++discarded_;break;}
    if(results_.tryPush(packet)){++published_;break;}
    idle();
   }
  }}catch(...){++failed_;closing_.store(true,std::memory_order_release);}
  // Retire queued inputs and worker-held resources here. Unconsumed output
  // slots are released at service shutdown if the consumer never polls them.
  packet.reset();request=Request{};while(requests_.tryPop(request))request=Request{};
  retire();scene.reset();lane.reset();cache.reset();pool.close();poolStats();active_.store(0,std::memory_order_release);closed_.store(true,std::memory_order_release);
 }
public:
 explicit Service(std::string ptx,bool prewarm=false):ptx_(std::move(ptx)),prewarm_(prewarm),worker_([this]{run();}){}
 ~Service(){closing_.store(true,std::memory_order_release);wake_.notify_one();if(worker_.joinable())worker_.join();}
 Service(const Service&)=delete;Service& operator=(const Service&)=delete;
 // Queue only an already prepared immutable plan. No native reads, build,
 // hashing, file I/O, waits or renderer joins happen on this entry point.
 bool request(const PlanView& plan,unsigned threads,uint64_t& ticket,unsigned debugFault=0,uint64_t debugDelay=0,unsigned passSamples=0,unsigned windowMs=0,bool refillFine=false,unsigned publishMs=0){
  owner();need(!closing_.load()&&!closed_.load(),"Mixed service closed");need(plan&&plan->source&&plan->source->routing&&threads>0&&threads<=12&&debugFault<=3&&(debugFault!=3||passSamples>0)&&debugDelay<=100000000&&passSamples<=plan->spp&&windowMs<=100&&(!windowMs||(!passSamples&&!debugDelay&&debugFault<=2)),"Invalid request");
  need(publishMs<=1000&&(!refillFine||windowMs>0)&&(!publishMs||windowMs>0),"Residency requires deadline rendering");
  const auto e=plan->source->routing->epoch;
  if(epoch_){auto old=*epoch_;need(e.session==old.session&&e.scene>=old.scene&&e.camera>=old.camera&&e.settings>=old.settings,"Stale scene epoch");need(!(e==old)||lastPlan_.lock()==plan,"Different plans share an epoch");}
  if(requests_.full())return false;
  auto n=next();Request value{n,plan,threads,debugFault,debugDelay,passSamples,windowMs,refillFine,publishMs};latest_.store(n,std::memory_order_release);
  // With one producer, the consumer can only make more space after full().
  if(!requests_.tryPush(value))std::terminate();
  ++submitted_;epoch_=e;lastPlan_=plan;ticket=n;wake_.notify_one();return true;
 }
 void cancel(){owner();latest_.store(next(),std::memory_order_release);wake_.notify_one();}
 // Success transfers one completed image to the caller. The caller controls its
 // lifetime; do not retain unbounded images. Stale images retire on the worker.
 PacketPtr poll(){
  owner();
  for(unsigned i=0;i<3;++i){
   if(held_){if(!retired_.tryPush(held_))return {};wake_.notify_one();}
   PacketPtr p;if(!results_.tryPop(p))return {};
   wake_.notify_one();if(!closing_.load()&&p->ticket==latest_.load(std::memory_order_acquire)&&(p->ticket!=failedTicket_.load(std::memory_order_acquire)||!p->error.empty()))return p;
   ++discarded_;held_=std::move(p);
  }
  return {};
 }
 void close(){owner();closing_.store(true,std::memory_order_release);wake_.notify_one();}
 // Shutdown only. Never call this from an interactive update.
 void join(){owner();close();if(worker_.joinable())worker_.join();}
 bool closed()const{return closed_.load(std::memory_order_acquire);}
 uint64_t active()const{return active_.load(std::memory_order_acquire);}
 uint64_t progress()const{return progress_.load(std::memory_order_acquire);}
 ServiceCounts counts()const{return {submitted_.load(),coalesced_.load(),started_.load(),published_.load(),cancelled_.load(),discarded_.load(),failed_.load(),reused_.load(),gpuStarts_.load(),gpuBuilt_.load(),gpuReused_.load(),partialPublished_.load(),partialSkipped_.load(),cpuCreated_.load(),cpuSubmitted_.load(),cpuCollected_.load(),cpuPasses_.load(),cpuJoined_.load(),cpuDiscarded_.load(),cpuPeak_.load(),cpuParked_.load()};}
};
}
