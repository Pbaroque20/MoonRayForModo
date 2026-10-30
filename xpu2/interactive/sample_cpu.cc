#include "sample_fixture.h"
#include <thread>
#include <vector>
#include <cstring>
using namespace xpu2::interactive;
extern "C" __declspec(dllexport) unsigned int checks(){return sampletest::checks();}
extern "C" __declspec(dllexport) int fill(unsigned long long first,unsigned int blocks,unsigned int* out,unsigned int threads){
    if(!out || threads<1 || threads>64)return 1;
    std::vector<std::thread> jobs;
    for(unsigned int t=0;t<threads;++t)jobs.emplace_back([=]{
        const auto begin=static_cast<unsigned long long>(blocks)*t/threads;
        const auto end=static_cast<unsigned long long>(blocks)*(t+1)/threads;
        for(auto j=begin;j<end;++j){auto w=sampletest::fixture(first+j);
            for(int k=0;k<4;++k){out[j*8+k]=w.v[k];float f=sample::unit(w.v[k]);std::memcpy(out+j*8+4+k,&f,4);}
        }
    });
    for(auto& job:jobs)job.join();return 0;
}
