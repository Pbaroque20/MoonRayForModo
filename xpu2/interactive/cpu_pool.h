// Private Windows persistent CPU workers. One feeder; bounded SPSC per worker.
#pragma once
#include "cpu_jobs.h"
#include "spsc_ring.h"
#include <atomic>
#include <thread>
#include <array>
#include <memory>
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
namespace xpu2::interactive::mixed {
struct CpuWork {cpu::PlanView plan;cpu::AccelView accel;Job job;std::shared_ptr<resume::Batch> continuation;unsigned steps=0;std::chrono::steady_clock::time_point until=std::chrono::steady_clock::time_point::max();};
struct CpuDone {cpu::PlanView plan;cpu::AccelView accel;Result result;};
struct PoolCounts {uint64_t created=0,submitted=0,collected=0,passes=0,failures=0,joined=0,discarded=0;unsigned outstanding=0,peakOutstanding=0,parked=0;std::array<uint64_t,12> perWorker{};};
class CpuWorker {
 struct Wake {
  HANDLE handle=CreateEventW(nullptr,FALSE,FALSE,nullptr);
  Wake(){cpu::need(handle!=nullptr,"CPU wake event creation");}
  ~Wake(){CloseHandle(handle);}Wake(const Wake&)=delete;
 } wake_;
 SpscRing<CpuWork,2> input_;SpscRing<CpuDone,2> output_;
 std::atomic<bool> stop_{false},parked_{false},broken_{false};std::thread thread_;
 void sleep()noexcept {parked_.store(true,std::memory_order_release);auto r=WaitForSingleObject(wake_.handle,INFINITE);parked_.store(false,std::memory_order_release);if(r!=WAIT_OBJECT_0){broken_.store(true,std::memory_order_release);stop_.store(true);}}
 void signal()noexcept {if(!SetEvent(wake_.handle)){broken_.store(true,std::memory_order_release);stop_.store(true);}}
 void run()noexcept {
  while(!stop_.load(std::memory_order_acquire)){
   CpuWork work;if(!input_.tryPop(work)){sleep();continue;}
   CpuDone done;done.plan=std::move(work.plan);done.accel=std::move(work.accel);
   try{done.result=work.continuation?cpuSlice(done.plan,done.accel,work.job,*work.continuation,work.steps,work.until):cpuJob(done.plan,done.accel,work.job);}
   catch(...){done.result=Result{};auto& r=done.result;r.epoch=work.job.epoch;r.sequence=work.job.sequence;r.count=work.job.count;for(unsigned i=0;i<r.count&&i<Capacity;++i){r.pixels[i].pixel=work.job.pixels[i];r.pixels[i].status=99;}}
   while(!stop_.load(std::memory_order_acquire)&&!output_.tryPush(done))sleep();
   // Scene/acceleration references move into the completion. They are released
   // by the feeder when collected, not retained by an idle thread or queue slot.
  }
 }
public:
 unsigned credits=0;
 CpuWorker():thread_([this]{run();}){}
 ~CpuWorker(){stop();join();}
 CpuWorker(const CpuWorker&)=delete;
 void stop()noexcept{stop_.store(true,std::memory_order_release);signal();}
 void join()noexcept{if(thread_.joinable())thread_.join();}
 bool broken()const{return broken_.load(std::memory_order_acquire);}
 bool parked()const{return parked_.load(std::memory_order_acquire);}
 bool submit(CpuWork& work){if(broken())throw std::runtime_error("CPU worker unavailable");if(!input_.tryPush(work))return false;signal();return true;}
 bool poll(CpuDone& done){if(!output_.tryPop(done))return false;signal();return true;}
};
class CpuPool {
 static constexpr unsigned Limit=12,Credits=2;
 std::thread::id owner_=std::this_thread::get_id();
 std::vector<std::unique_ptr<CpuWorker>> workers_;PoolCounts counts_;
 unsigned active_=0,cursor_=0,pollCursor_=0;bool inPass_=false,closed_=false;
 void owner()const{if(std::this_thread::get_id()!=owner_)throw std::logic_error("CPU pool requires its feeder");}
 void healthy()const{for(auto& w:workers_)cpu::need(!w->broken(),"CPU worker wake failure");}
public:
 CpuPool(){workers_.reserve(Limit);}CpuPool(const CpuPool&)=delete;
 ~CpuPool(){close();}
 void begin(unsigned threads){owner();cpu::need(!closed_&&!inPass_&&!counts_.outstanding&&threads<=Limit,"CPU pool pass overlap or worker budget");
  healthy();while(workers_.size()<threads){workers_.push_back(std::make_unique<CpuWorker>());++counts_.created;}
  active_=threads;cursor_=pollCursor_=0;inPass_=true;++counts_.passes;
 }
 bool submit(cpu::PlanView plan,cpu::AccelView accel,const Job& job,std::shared_ptr<resume::Batch> continuation={},unsigned steps=0,std::chrono::steady_clock::time_point until=std::chrono::steady_clock::time_point::max()){owner();cpu::need(inPass_&&!closed_&&plan&&accel,"CPU pool submission outside pass");cpu::need(same(job,config(plan)),"Invalid CPU pool job");healthy();
  for(unsigned attempt=0;attempt<active_;++attempt){auto index=(cursor_+attempt)%active_;auto& w=*workers_[index];if(w.credits>=Credits)continue;
   CpuWork work{plan,accel,job,continuation,steps,until};if(!w.submit(work))continue;++w.credits;++counts_.submitted;++counts_.outstanding;++counts_.perWorker[index];counts_.peakOutstanding=std::max(counts_.peakOutstanding,counts_.outstanding);cursor_=(index+1)%active_;return true;
  }return false;
 }
 bool poll(Result& result){owner();cpu::need(inPass_&&!closed_,"CPU pool poll outside pass");healthy();
  for(unsigned attempt=0;attempt<workers_.size();++attempt){auto index=(pollCursor_+attempt)%unsigned(workers_.size());auto& w=*workers_[index];if(!w.credits)continue;CpuDone done;if(!w.poll(done))continue;
   cpu::need(counts_.outstanding>0,"CPU completion without credit");--w.credits;--counts_.outstanding;++counts_.collected;result=std::move(done.result);for(unsigned i=0;i<result.count&&i<Capacity;++i)if(result.pixels[i].status){++counts_.failures;break;}pollCursor_=(index+1)%unsigned(workers_.size());return true;
  }return false;
 }
 void finish(){owner();cpu::need(inPass_&&!counts_.outstanding,"CPU pass still owns work");inPass_=false;active_=0;}
 // Only on an unwinding feeder. Accepted complete-sample jobs drain before reuse.
 // If the worker itself breaks, the pool is closed and cannot be reused.
 void abandon()noexcept{try{if(!inPass_||closed_)return;Result r;while(counts_.outstanding){if(!poll(r))std::this_thread::yield();}finish();}catch(...){close();}}
 PoolCounts counts()const{owner();auto c=counts_;for(auto& w:workers_)c.parked+=w->parked()?1:0;return c;}
 bool closed()const{return closed_;}
 void close()noexcept{if(closed_)return;closed_=true;for(auto& w:workers_)w->stop();for(auto& w:workers_){w->join();++counts_.joined;}workers_.clear();counts_.discarded+=counts_.outstanding;counts_.outstanding=0;inPass_=false;active_=0;}
};
struct CpuPass {
 CpuPool& pool;bool done=false;
 CpuPass(CpuPool& p,unsigned threads):pool(p){pool.begin(threads);}
 ~CpuPass(){if(!done)pool.abandon();}
 void finish(){pool.finish();done=true;}
};
}
