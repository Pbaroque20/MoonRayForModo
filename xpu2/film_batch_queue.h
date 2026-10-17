// Bounded owned numeric jobs. Native render state never enters this queue.
#pragma once
#include <array>
#include <condition_variable>
#include <deque>
#include <functional>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>
#include <algorithm>
#include <stdexcept>
namespace filmqueue {
constexpr unsigned RequestSlots=16, BatchSlots=128, Capacity=16;
struct Job {
 unsigned count=0; bool done=false;
 std::array<float,RequestSlots*8*24> input{},lambert{};
 std::array<float,RequestSlots*8*8> reference{},native{},output{};
 std::array<int,RequestSlots> masks{},shaderMasks{},accepted{};
};
struct Stats {
 unsigned long long submitted=0,returned=0,declined=0,batches=0,combined=0,
  maxJobs=0,maxSlots=0,maxOutstanding=0,duringService=0,exceptions=0;
};
class Queue {
public:
 using Batch=std::vector<std::shared_ptr<Job>>;
 using Execute=std::function<void(const Batch&)>;
 explicit Queue(Execute execute):execute_(std::move(execute)),worker_([this]{work();}){}
 Queue(const Queue&)=delete; Queue& operator=(const Queue&)=delete;
 ~Queue(){close();}
 // The caller owns its native stack until this returns. Queue/worker own only Job.
 bool submit(const std::shared_ptr<Job>& job){
  if(!job||!job->count||job->count>RequestSlots)throw std::invalid_argument("Invalid film job");
  std::unique_lock<std::mutex> lock(mutex_);
  if(closing_||outstanding_>=Capacity){++stats_.declined;return false;}
  if(job->done)throw std::invalid_argument("Film job already returned");
  for(const auto& active:admitted_)if(active==job.get())throw std::invalid_argument("Duplicate film job");
  pending_.push_back(job);admitted_.push_back(job.get());++outstanding_;++stats_.submitted;
  if(servicing_)++stats_.duringService;
  stats_.maxOutstanding=std::max(stats_.maxOutstanding,(unsigned long long)outstanding_);
  wake_.notify_one();done_.wait(lock,[&]{return job->done;});
  admitted_.erase(std::find(admitted_.begin(),admitted_.end(),job.get()));
  --outstanding_;++stats_.returned;done_.notify_all();return true;
 }
 void close(){
  std::lock_guard<std::mutex> serial(closeMutex_);
  {std::lock_guard<std::mutex> lock(mutex_);closing_=true;wake_.notify_all();}
  if(worker_.joinable())worker_.join();
  std::unique_lock<std::mutex> lock(mutex_);done_.wait(lock,[&]{return outstanding_==0;});
 }
 Stats stats(){std::lock_guard<std::mutex> lock(mutex_);return stats_;}
private:
 void work(){
  for(;;){
   Batch batch;unsigned slots=0;
   {std::unique_lock<std::mutex> lock(mutex_);wake_.wait(lock,[&]{return closing_||!pending_.empty();});
    if(pending_.empty())return;
    while(!pending_.empty()&&slots+pending_.front()->count<=BatchSlots){
     slots+=pending_.front()->count;batch.push_back(pending_.front());pending_.pop_front();
    }
    servicing_=true;++stats_.batches;if(batch.size()>1)++stats_.combined;
    stats_.maxJobs=std::max(stats_.maxJobs,(unsigned long long)batch.size());
    stats_.maxSlots=std::max(stats_.maxSlots,(unsigned long long)slots);
   }
   bool failed=false;
   try{execute_(batch);}catch(...){failed=true;for(auto& job:batch)job->accepted.fill(0);}
   {std::lock_guard<std::mutex> lock(mutex_);servicing_=false;if(failed)++stats_.exceptions;
    for(auto& job:batch)job->done=true;done_.notify_all();}
  }
 }
 Execute execute_;
 std::mutex mutex_,closeMutex_;std::condition_variable wake_,done_;
 std::deque<std::shared_ptr<Job>> pending_;std::vector<Job*> admitted_;
 unsigned outstanding_=0;bool closing_=false,servicing_=false;Stats stats_;
 // Last: all synchronization state must exist before the worker starts.
 std::thread worker_;
};
}
