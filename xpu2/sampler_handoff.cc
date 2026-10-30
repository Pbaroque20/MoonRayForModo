// Actual CPU-thread handoffs of serialized sampler state; no GPU or scene edits.
#include "sampler_state.h"
#include <atomic>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <deque>
#include <exception>
#include <mutex>
#include <thread>
using namespace moonray::pbr;
struct Case { xpu2::SamplerState state; unsigned count; };
struct Job { size_t id; std::vector<uint8_t> bytes; bool waited; int previous; };
struct Part { xpu2::SamplerState state; std::vector<unsigned> bits; };
static unsigned bits(float value) { unsigned word; std::memcpy(&word,&value,4); return word; }
template<unsigned D>
Part advance(xpu2::SamplerState state,unsigned count) {
    xpu2::SamplerCursor<D> cursor(state);
    Part result;
    for(unsigned i=0;i<count;++i)
        for(float value:cursor.draw()) result.bits.push_back(bits(value));
    result.state=cursor.snapshot();
    return result;
}
static Part advance(xpu2::SamplerState state,unsigned count) {
    return state.dimensions==1 ? advance<1>(state,count) :
           state.dimensions==2 ? advance<2>(state,count) : advance<3>(state,count);
}
static unsigned rejectionChecks() {
    unsigned passed=0;
    const xpu2::SamplerState state{{0,1,2,3,4,5},2,0,16,0,0};
    auto reject=[&](const std::vector<uint8_t>& bytes) {
        try { xpu2::decode(bytes); } catch(const std::exception&) { ++passed; return; }
        throw std::runtime_error("Invalid state accepted");
    };
    auto bytes=xpu2::encode(state);
    auto shortBytes=bytes;shortBytes.pop_back();reject(shortBytes);
    auto corrupt=bytes;corrupt[32]^=1;reject(corrupt);
    auto modified=[&](unsigned word,uint32_t value) {
        auto data=bytes;
        for(unsigned i=0;i<4;++i) data[word*4+i]=uint8_t(value>>(i*8));
        const auto hash=xpu2::checksum(data,56);
        for(unsigned i=0;i<4;++i) data[56+i]=uint8_t(hash>>(i*8));
        reject(data);
    };
    modified(0,0);modified(1,2);modified(7,5);modified(2,4);
    modified(6,2);modified(4,0);modified(5,17);
    auto exhausted=state;exhausted.next=16;
    try { xpu2::SamplerCursor<2>(exhausted).draw(); }
    catch(const std::out_of_range&) { ++passed; }
    try { xpu2::SamplerCursor<1> wrong(state); }
    catch(const std::invalid_argument&) { ++passed; }
    if(passed!=11) throw std::runtime_error("Missing state guard");
    return passed;
}
int main(int argc,char** argv) {
    try {
        const unsigned workers=argc==2 ? unsigned(std::atoi(argv[1])) : 1;
        if(workers<1 || workers>16) return 2;
        const unsigned guards=rejectionChecks();
        std::vector<Case> cases;
        for(unsigned dims:{1u,2u,3u}) for(unsigned depth:{0u,2u,3u})
        for(unsigned pseudo:{0u,1u}) for(unsigned total:{~0u,1u,16u,64u})
        for(unsigned seed:{0u,19u,0xffffffffu})
        for(auto purpose:{SequenceType::Bsdf,SequenceType::Light,SequenceType::RussianRouletteBsdf}) {
            xpu2::SamplerState state{{depth,(77u<<16)|96u,seed%3,unsigned(purpose),0,seed},
                                     dims,depth,total,0,pseudo};
            cases.push_back({state,total==~0u?65:total});
        }
        std::vector<std::vector<unsigned>> rows(cases.size());
        std::deque<Job> queue;
        for(size_t i=0;i<cases.size();++i) queue.push_back({i,xpu2::encode(cases[i].state),false,-1});
        std::mutex mutex;std::condition_variable changed;
        size_t remaining=cases.size();
        unsigned waits=0,retries=0,transfers=0;
        std::vector<unsigned> work(workers,0);
        std::exception_ptr error;
        std::vector<std::thread> threads;
        for(unsigned w=0;w<workers;++w) threads.emplace_back([&,w]() {
            try {
                for(;;) {
                    Job job;
                    {
                        std::unique_lock<std::mutex> lock(mutex);
                        changed.wait(lock,[&]{return error || remaining==0 || !queue.empty();});
                        if(error || remaining==0) return;
                        job=std::move(queue.front());queue.pop_front();
                        // Simulate a missing resource: defer without advancing ANY state.
                        if(!job.waited) {
                            job.waited=true;queue.push_back(std::move(job));++waits;
                            changed.notify_all();continue;
                        }
                    }
                    const auto state=xpu2::decode(job.bytes);
                    const unsigned count=std::min(7u,cases[job.id].count-state.next);
                    const auto part=advance(state,count);
                    const bool retry=(job.id+state.next)%5==0;
                    if(retry && advance(xpu2::decode(job.bytes),count).bits!=part.bits)
                        throw std::runtime_error("Retry changed native samples");
                    {
                        std::lock_guard<std::mutex> lock(mutex);
                        auto& row=rows[job.id];
                        if(row.size()!=size_t(state.next)*state.dimensions)
                            throw std::runtime_error("Duplicate or skipped contribution");
                        row.insert(row.end(),part.bits.begin(),part.bits.end());
                        ++work[w];if(retry) ++retries;
                        if(job.previous>=0 && job.previous!=int(w)) ++transfers;
                        if(part.state.next<cases[job.id].count)
                            queue.push_back({job.id,xpu2::encode(part.state),false,int(w)});
                        else --remaining;
                        changed.notify_all();
                    }
                }
            } catch(...) {
                std::lock_guard<std::mutex> lock(mutex);error=std::current_exception();changed.notify_all();
            }
        });
        for(auto& thread:threads) thread.join();
        if(error) std::rethrow_exception(error);
        std::printf("{\"schema\":2,\"simd_width\":%u,\"cases\":%zu,\"guards\":%u,\"waits\":%u,\"retries\":%u,\"transfers\":%u,\"work\":[",
                    unsigned(kSIMDSize),rows.size(),guards,waits,retries,transfers);
        for(unsigned w=0;w<workers;++w) std::printf("%s%u",w?",":"",work[w]);
        std::printf("]}\n");
        for(size_t i=0;i<rows.size();++i) {
            std::printf("{\"id\":%zu,\"values\":[",i);
            for(size_t j=0;j<rows[i].size();++j) std::printf("%s%u",j?",":"",rows[i][j]);
            std::printf("]}\n");
        }
        return 0;
    } catch(const std::exception& error) { std::fprintf(stderr,"%s\n",error.what());return 1; }
}
