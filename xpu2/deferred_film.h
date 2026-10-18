// Owned terminal-path continuation. No ray, arena, scene, film or TLS pointers.
#pragma once
#include <array>
#include <algorithm>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <cstring>
#include <deque>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <vector>
namespace xpu2::deferredfilm {
struct Sample {
    std::array<float,4> rgba{};
    float weight=0;
    uint32_t pixel=0,subpixel=0,tilePass=0;
};
using Samples=std::vector<Sample>;
struct Packet {uint64_t epoch=0,revision=0,owner=0,serial=0;Samples original,result;bool failed=false,revoked=false;};
struct Stats {uint64_t admitted=0,resumed=0,revoked=0,failed=0,declined=0;size_t peakJobs=0,peakBytes=0;};
// Each owner is serialized by its native worker. Worker callbacks may only
// operate on owned samples. All results retain credits until owner retirement.
class Queue {
    struct Job {Packet packet;bool ready=false;};
    mutable std::mutex mutex_;std::condition_variable cv_;
    std::map<uint64_t,std::deque<std::shared_ptr<Job>>> owners_;
    std::deque<std::shared_ptr<Job>> pending_;
    std::function<void(Samples&)> process_;
    std::thread worker_;
    size_t maxJobs_,maxBytes_,jobs_=0,bytes_=0;
    uint64_t epoch_=0,revision_=0,serial_=0;
    bool stopping_=false;Stats stats_;
    static size_t cost(const Samples& s){return s.size()*sizeof(Sample)*2;}
    static bool valid(const Samples& a,const Samples& b){
        if(a.size()!=b.size())return false;
        for(size_t i=0;i<a.size();++i){
            if(a[i].pixel!=b[i].pixel||a[i].subpixel!=b[i].subpixel||a[i].tilePass!=b[i].tilePass||
               std::memcmp(&a[i].weight,&b[i].weight,sizeof(float)))return false;
            // Native sources use fast-math: inspect exponent bits so that compiler
            // assumptions cannot erase the rejection of NaN/Inf completions.
            for(float f:b[i].rgba){uint32_t bits;std::memcpy(&bits,&f,sizeof(bits));if((bits&0x7f800000u)==0x7f800000u)return false;}
        }return true;
    }
    void work(){
        for(;;){std::shared_ptr<Job> j;
            {std::unique_lock<std::mutex> lock(mutex_);cv_.wait(lock,[&]{return stopping_||!pending_.empty();});
             if(pending_.empty())return;j=pending_.front();pending_.pop_front();}
            // A failed backend returns the intact native contribution, not black.
            try{process_(j->packet.result);j->packet.failed=!valid(j->packet.original,j->packet.result);}
            catch(...){j->packet.failed=true;}
            {std::lock_guard<std::mutex> lock(mutex_);j->ready=true;}cv_.notify_all();
        }
    }
public:
    explicit Queue(std::function<void(Samples&)> process,size_t maxJobs=32,size_t maxBytes=8*1024*1024)
      :process_(std::move(process)),maxJobs_(maxJobs),maxBytes_(maxBytes){
        if(!maxJobs||!maxBytes||!process_)throw std::invalid_argument("Invalid film queue limits");
        worker_=std::thread([this]{work();});
    }
    ~Queue(){shutdown();}
    Queue(const Queue&)=delete;Queue& operator=(const Queue&)=delete;
    void begin(uint64_t epoch,uint64_t revision){std::lock_guard<std::mutex> lock(mutex_);
        if(stopping_||!epoch||epoch<=epoch_)throw std::logic_error("Film epoch must advance");
        epoch_=epoch;revision_=revision; // outstanding old packets remain charged and revoked
    }
    bool submit(uint64_t epoch,uint64_t revision,uint64_t owner,const Samples& samples){
        std::lock_guard<std::mutex> lock(mutex_);
        if(stopping_||!owner||!epoch||epoch!=epoch_||revision!=revision_||samples.empty()||
           samples.size()>maxBytes_/sizeof(Sample)/2||jobs_>=maxJobs_||cost(samples)>maxBytes_-bytes_){++stats_.declined;return false;}
        auto j=std::make_shared<Job>();j->packet={epoch,revision,owner,++serial_,samples,samples,false,false};
        auto& ownerQueue=owners_[owner];ownerQueue.push_back(j);
        try{pending_.push_back(j);}catch(...){ownerQueue.pop_back();if(ownerQueue.empty())owners_.erase(owner);throw;}
        ++jobs_;bytes_+=cost(samples);++stats_.admitted;
        stats_.peakJobs=std::max(stats_.peakJobs,jobs_);stats_.peakBytes=std::max(stats_.peakBytes,bytes_);
        cv_.notify_all();return true;
    }
    // FIFO per owner preserves the original film batch boundaries and sums.
    bool take(uint64_t owner,bool wait,Packet& out){std::unique_lock<std::mutex> lock(mutex_);
        auto i=owners_.find(owner);if(i==owners_.end())return false;
        auto j=i->second.front();if(wait)cv_.wait(lock,[&]{return j->ready;});else if(!j->ready)return false;
        j->packet.revoked=j->packet.epoch!=epoch_||j->packet.revision!=revision_;
        bytes_-=cost(j->packet.original);--jobs_;
        if(j->packet.revoked)++stats_.revoked;else{++stats_.resumed;if(j->packet.failed)++stats_.failed;}
        out=std::move(j->packet);i->second.pop_front();if(i->second.empty())owners_.erase(i);return true;
    }
    size_t outstanding()const{std::lock_guard<std::mutex> lock(mutex_);return jobs_;}
    Stats stats()const{std::lock_guard<std::mutex> lock(mutex_);return stats_;}
    void shutdown(){
        {std::lock_guard<std::mutex> lock(mutex_);stopping_=true;}cv_.notify_all();
        if(worker_.joinable())worker_.join(); // no in-flight access to destroyed storage
    }
};
} // namespace
