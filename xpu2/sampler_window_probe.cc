// Native boundary test: compare unchanged sampler with serialized continuation.
#include "sampler_window.h"
#include "sampler_exchange.h"
#include <algorithm>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <thread>
#include <vector>
using namespace moonray::pbr;
struct Case {unsigned dims,depth,seed,purpose,origin;};
struct Row {Case c;unsigned begin,hash;std::vector<unsigned> baseline,restored,naive,anchors;};
static unsigned bits(float value){unsigned word;std::memcpy(&word,&value,4);return word;}
template<unsigned D>
Row measure(Case c) {
    xpu2::SamplerState state{{c.depth,(77u<<16)|96u,c.seed%3,c.purpose,0,c.seed},
                             D,c.depth,~0u,c.origin,0};
    IntegratorSample<D> baseline(state.sid(),state.total,state.next);
    xpu2::WindowCursor<D> live({state,c.origin});
    Row row{c,std::max(1000u,c.origin),state.sid().private_test(),{},{},{},{}};
    for(unsigned index=c.origin;index<1048;++index) {
        auto snapshot=live.snapshot();
        float expected[D];baseline.getSample(expected,c.depth);
        const auto continuous=live.draw();
        for(unsigned d=0;d<D;++d)
            if(bits(expected[d])!=bits(continuous[d]))throw std::runtime_error("Live wrapper drift");
        if(index<row.begin)continue;
        const auto wire=xpu2::encodeWindow(snapshot);
        xpu2::WindowCursor<D> restored(xpu2::decodeWindow(wire));
        const auto value=restored.draw();
        IntegratorSample<D> naive(state.sid(),state.total,index);
        float indexOnly[D];naive.getSample(indexOnly,c.depth);
        row.anchors.push_back(snapshot.cacheBegin);
        for(unsigned d=0;d<D;++d) {
            row.baseline.push_back(bits(expected[d]));
            row.restored.push_back(bits(value[d]));
            row.naive.push_back(bits(indexOnly[d]));
        }
    }
    return row;
}
static unsigned guards() {
    const xpu2::WindowState valid{{{0,1,2,3,4,5},2,0,~0u,1015,0},1008};
    const auto wire=xpu2::encodeWindow(valid);
    unsigned count=0;
    auto reject=[&](std::vector<uint8_t> bytes) {
        try{xpu2::decodeWindow(bytes);}catch(const std::exception&){++count;return;}
        throw std::runtime_error("Bad window accepted");
    };
    auto bytes=wire;bytes.pop_back();reject(bytes);
    bytes=wire;bytes[56]^=1;reject(bytes);
    auto replace=[&](unsigned offset,unsigned word){
        bytes=wire;for(unsigned i=0;i<4;++i)bytes[offset+i]=uint8_t(word>>(8*i));
        auto h=xpu2::checksum(bytes,60);
        for(unsigned i=0;i<4;++i)bytes[60+i]=uint8_t(h>>(8*i));
        reject(bytes);
    };
    replace(56,1016);replace(56,1006);replace(4,1);
    try{xpu2::decode(wire);}catch(const std::exception&){++count;}
    if(count!=6)throw std::runtime_error("Missing window guard");
    return count;
}
static void values(const char* label,const std::vector<unsigned>& v) {
    std::printf(",\"%s\":[",label);
    for(size_t i=0;i<v.size();++i)std::printf("%s%u",i?",":"",v[i]);
    std::printf("]");
}
int main(int argc,char** argv) {
    const unsigned workers=argc>=2 ? unsigned(std::atoi(argv[1])) : 1;
    if(workers<1 || workers>16)return 2;
    if(argc==5 && std::strcmp(argv[2],"exchange")==0)return xpu2::exchange(argv[3],argv[4],workers);
    if(argc==3 && std::strcmp(argv[2],"moebius")==0) {
        std::ofstream file("moebius.bin",std::ios::binary);
        file.write(reinterpret_cast<const char*>(moebiusTransformationValues),
                   kMoebiusTransformationSize*sizeof(float));
        file.close();if(!file)return 3;
        std::printf("{\"count\":%u}\n",unsigned(kMoebiusTransformationSize));return 0;
    }
    const auto guardCount=guards();
    std::vector<Case> cases;
    for(unsigned dims:{1u,2u,3u})for(unsigned depth:{0u,2u})
    for(unsigned seed:{0u,19u,0xffffffffu})for(unsigned purpose:{0u,1u,2u})
    for(unsigned origin:{0u,1u,7u,1009u,1013u,1015u})
        cases.push_back({dims,depth,seed,purpose,origin});
    std::vector<Row> rows(cases.size());std::atomic<size_t> next{0};
    std::vector<std::thread> threads;
    for(unsigned w=0;w<workers;++w)threads.emplace_back([&]{
        for(size_t i;(i=next.fetch_add(1))<cases.size();) {
            auto c=cases[i];rows[i]=c.dims==1?measure<1>(c):c.dims==2?measure<2>(c):measure<3>(c);
        }
    });
    for(auto& thread:threads)thread.join();
    std::printf("{\"schema\":4,\"simd_width\":%u,\"cases\":%zu,\"guards\":%u}\n",
                unsigned(kSIMDSize),rows.size(),guardCount);
    for(size_t i=0;i<rows.size();++i) {
        const auto& r=rows[i];const auto c=r.c;
        std::printf("{\"id\":%zu,\"dims\":%u,\"depth\":%u,\"seed\":%u,\"purpose\":%u,\"origin\":%u,\"begin\":%u,\"sequence_hash\":%u",
                    i,c.dims,c.depth,c.seed,c.purpose,c.origin,r.begin,r.hash);
        values("baseline",r.baseline);values("restored",r.restored);
        values("index_only",r.naive);values("anchors",r.anchors);std::printf("}\n");
    }
}
