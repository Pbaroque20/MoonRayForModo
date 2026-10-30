// Private experimental CPU service. No production routing or GPU implementation.
#pragma once
#include "cpu_lane.h"
#include "spsc_ring.h"
#include <condition_variable>
#include <optional>
namespace xpu2::interactive::cpu {
struct Request {uint64_t ticket=0;PlanView plan;unsigned threads=0;};
struct Packet {
 uint64_t ticket=0;Epoch epoch{};Image image;std::string error;
 // Unqualified native pixels cannot be labelled fidelity tier N.
 char tier='D';bool qualified=false;
};
using PacketPtr=std::unique_ptr<Packet>;
struct ServiceCounts {uint64_t submitted,coalesced,started,published,cancelled,discarded,failed,reusedAcceleration;};
class Service {
 const std::thread::id owner_=std::this_thread::get_id();
 SpscRing<Request,4> requests_;
 SpscRing<PacketPtr,2> results_;
 // Host returns obsolete packets to the worker for destruction. If this ring
 // is full, poll simply applies backpressure; no large buffer is freed there.
 SpscRing<PacketPtr,4> retired_;PacketPtr held_;
 std::atomic<uint64_t> latest_{0},active_{0},progress_{0};
 std::atomic<bool> closing_{false},closed_{false};
 std::atomic<uint64_t> submitted_{0},coalesced_{0},started_{0},published_{0},cancelled_{0},discarded_{0},failed_{0},reused_{0};
 std::weak_ptr<const Plan> lastPlan_;std::optional<Epoch> epoch_;
 std::mutex waitMutex_;std::condition_variable wake_;std::thread worker_;
 void owner()const{if(std::this_thread::get_id()!=owner_)throw std::logic_error("CPU service requires its coordinator");}
 uint64_t next()const {auto n=latest_.load(std::memory_order_relaxed);need(n!=UINT64_MAX,"Service generation exhausted");return n+1;}
 void idle(){std::unique_lock<std::mutex> lock(waitMutex_);wake_.wait_for(lock,std::chrono::milliseconds(1));}
 void retire(){PacketPtr p;while(retired_.tryPop(p))p.reset();}
 void run()noexcept {
  AccelView cache;Request request;PacketPtr packet;
  try{while(!closing_.load(std::memory_order_acquire)){
   retire();Request incoming;
   while(requests_.tryPop(incoming)){if(request.plan)++coalesced_;request=std::move(incoming);}
   if(!request.plan){idle();continue;}
   if(request.ticket!=latest_.load(std::memory_order_acquire)){++discarded_;request=Request{};continue;}
   auto ticket=request.ticket;progress_.store(0);active_.store(ticket,std::memory_order_release);++started_;
   packet=std::make_unique<Packet>();packet->ticket=ticket;packet->epoch=request.plan->source->routing->epoch;
   try{
    auto prepared=acceleration(request.plan,cache);if(prepared==cache)++reused_;cache=std::move(prepared);
    packet->image=render(request.plan,cache,request.threads,&closing_,&progress_,&latest_,ticket);
    if(packet->image.cancelled)++cancelled_;
   }catch(const std::exception& error){packet->error=error.what();++failed_;}
   catch(...){packet->error="Unknown native worker failure";++failed_;}
   request=Request{};active_.store(0,std::memory_order_release);
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
  retire();cache.reset();active_.store(0,std::memory_order_release);closed_.store(true,std::memory_order_release);
 }
public:
 Service():worker_([this]{run();}){}
 ~Service(){closing_.store(true,std::memory_order_release);wake_.notify_one();if(worker_.joinable())worker_.join();}
 Service(const Service&)=delete;Service& operator=(const Service&)=delete;
 // Queue only an already prepared immutable plan. No native reads, build,
 // hashing, file I/O, waits or renderer joins happen on this entry point.
 bool request(const PlanView& plan,unsigned threads,uint64_t& ticket){
  owner();need(!closing_.load()&&!closed_.load(),"CPU service closed");need(plan&&plan->source&&plan->source->routing&&threads>0&&threads<=64,"Invalid request");
  const auto e=plan->source->routing->epoch;
  if(epoch_){auto old=*epoch_;need(e.session==old.session&&e.scene>=old.scene&&e.camera>=old.camera&&e.settings>=old.settings,"Stale scene epoch");need(!(e==old)||lastPlan_.lock()==plan,"Different plans share an epoch");}
  if(requests_.full())return false;
  auto n=next();Request value{n,plan,threads};latest_.store(n,std::memory_order_release);
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
   wake_.notify_one();if(!closing_.load()&&p->ticket==latest_.load(std::memory_order_acquire))return p;
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
 ServiceCounts counts()const{return {submitted_.load(),coalesced_.load(),started_.load(),published_.load(),cancelled_.load(),discarded_.load(),failed_.load(),reused_.load()};}
};
}
