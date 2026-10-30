// Isolated file-based native continuation endpoint; not a renderer IPC protocol.
#pragma once
#include "sampler_window.h"
#include <atomic>
#include <cstring>
#include <fstream>
#include <thread>
namespace xpu2 {
inline uint32_t readWord(std::istream& in) {
    unsigned char b[4];if(!in.read(reinterpret_cast<char*>(b),4))throw std::runtime_error("Truncated batch");
    return uint32_t(b[0])|(uint32_t(b[1])<<8)|(uint32_t(b[2])<<16)|(uint32_t(b[3])<<24);
}
inline void writeWord(std::ostream& out,uint32_t n) {
    for(unsigned i=0;i<4;++i)out.put(char(n>>(8*i)));
}
struct ExchangeRecord {
    std::vector<uint8_t> state;
    uint32_t length;
    std::array<uint32_t,5> result{{2,0,0,0,0}};
};
template<unsigned D> void exchangeDraw(ExchangeRecord& record,WindowState state) {
    WindowCursor<D> cursor(state);
    const auto values=cursor.draw();
    std::array<uint32_t,5> result{{0,state.sampler.sid().private_test(),0,0,0}};
    for(unsigned i=0;i<D;++i)std::memcpy(&result[i+2],&values[i],4);
    auto next=encodeWindow(cursor.snapshot());
    record.state=std::move(next);record.result=result;
}
inline int exchange(const char* input,const char* output,unsigned workers) {
    try {
        std::ifstream in(input,std::ios::binary);
        if(readWord(in)!=0x32425758u)throw std::runtime_error("Bad batch magic"); // XWB2
        const auto count=readWord(in);
        if(!count || count>32768)throw std::runtime_error("Bad batch count");
        std::vector<ExchangeRecord> records(count);
        for(auto& r:records) {
            r.length=readWord(in);r.state.resize(64);
            if(!in.read(reinterpret_cast<char*>(r.state.data()),64))throw std::runtime_error("Truncated state");
        }
        if(in.peek()!=std::char_traits<char>::eof())throw std::runtime_error("Trailing batch data");
        std::atomic<size_t> next{0};std::vector<std::thread> threads;
        for(unsigned w=0;w<workers;++w)threads.emplace_back([&]{
            for(size_t i;(i=next.fetch_add(1))<records.size();) {
                auto& r=records[i];if(r.length!=64)continue;
                try {
                    auto s=decodeWindow(r.state);
                    if(s.sampler.dimensions==1)exchangeDraw<1>(r,s);
                    else if(s.sampler.dimensions==2)exchangeDraw<2>(r,s);
                    else exchangeDraw<3>(r,s);
                }catch(const std::invalid_argument&){}catch(const std::out_of_range&){}
            }
        });
        for(auto& t:threads)t.join();
        std::ofstream out(output,std::ios::binary);writeWord(out,0x324f5758u);writeWord(out,count); // XWO2
        for(const auto& r:records) {
            out.write(reinterpret_cast<const char*>(r.state.data()),64);
            for(auto word:r.result)writeWord(out,word);
        }
        out.close();if(!out)throw std::runtime_error("Cannot write batch results");return 0;
    }catch(const std::exception& e) {std::fprintf(stderr,"%s\n",e.what());return 3;}
}
}
