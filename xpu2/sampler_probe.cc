// Standalone native sampler corpus. No scene, image, GPU, or installed kit writes.
#include <moonray/rendering/pbr/sampler/IntegratorSample.h>
#include <algorithm>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <limits>
#include <numeric>
#include <random>
#include <thread>
#include <vector>
using namespace moonray::pbr;

struct Case { unsigned dims,depth,total,seed,purpose; bool pseudo; };
struct Row { Case c; unsigned hash; std::vector<unsigned> baseline,chunked,reordered,naive; };
static unsigned bits(float value) { unsigned word; std::memcpy(&word,&value,4); return word; }

template<unsigned D>
static Row measure(Case c) {
    const unsigned unknown=std::numeric_limits<unsigned>::max();
    const unsigned count=c.total==unknown ? 65 : c.total;
    const SequenceID sid(c.depth, (77u<<16)|96u, c.seed%3, c.purpose, 0u, c.seed);
    Row row{c,sid.private_test(),{},{},{},{}};
    auto collect=[&](IntegratorSample<D>& sampler, std::vector<unsigned>& out, unsigned offset, unsigned n) {
        for(unsigned i=0;i<n;++i) {
            float values[D]; sampler.getSample(values,c.depth);
            for(unsigned d=0;d<D;++d) out[(offset+i)*D+d]=bits(values[d]);
        }
    };
    row.baseline.resize(count*D); row.chunked.resize(count*D);
    row.reordered.resize(count*D); row.naive.resize(count*D);
    IntegratorSample<D> initial(sid,c.total,0);
    initial.setUsePseudoRandom(c.pseudo);
    collect(initial,row.baseline,0,count);
    const unsigned chunks[]={1,7,8,9,31};
    for(unsigned i=0,k=0;i<count;++k) {
        const unsigned n=std::min(chunks[k%5],count-i);
        IntegratorSample<D> restored(sid,c.total,i);
        restored.setUsePseudoRandom(c.pseudo);
        collect(restored,row.chunked,i,n);
        i+=n;
    }
    std::vector<unsigned> order(count);
    std::iota(order.begin(),order.end(),0);
    std::mt19937 rng(12345+c.seed); std::shuffle(order.begin(),order.end(),rng);
    for(unsigned i:order) {
        IntegratorSample<D> restored(sid,c.total,i);
        restored.setUsePseudoRandom(c.pseudo);
        collect(restored,row.reordered,i,1);
        // Negative control: resume() discards known total-sample-count state.
        IntegratorSample<D> naive(sid);
        naive.resume(sid,i); naive.setUsePseudoRandom(c.pseudo);
        collect(naive,row.naive,i,1);
    }
    return row;
}
static void values(const char* name,const std::vector<unsigned>& data) {
    std::printf(",\"%s\":[",name);
    for(size_t i=0;i<data.size();++i) std::printf("%s%u",i?",":"",data[i]);
    std::printf("]");
}
int main(int argc,char** argv) {
    const unsigned workers=argc==2 ? unsigned(std::atoi(argv[1])) : 1;
    if(workers<1 || workers>16) return 2;
    std::vector<Case> cases;
    for(unsigned dims:{1u,2u,3u}) for(unsigned depth:{0u,2u,3u})
    for(unsigned pseudo:{0u,1u}) for(unsigned total:{~0u,1u,16u,64u})
    for(unsigned seed:{0u,19u,0xffffffffu})
    for(auto purpose:{SequenceType::Bsdf,SequenceType::Light,SequenceType::RussianRouletteBsdf})
        cases.push_back({dims,depth,total,seed,unsigned(purpose),bool(pseudo)});
    std::vector<Row> rows(cases.size());
    std::atomic<size_t> next{0};
    std::vector<std::thread> threads;
    for(unsigned w=0;w<workers;++w) threads.emplace_back([&](){
        for(size_t i;(i=next.fetch_add(1))<cases.size();) {
            const auto c=cases[i];
            rows[i]=c.dims==1 ? measure<1>(c) : c.dims==2 ? measure<2>(c) : measure<3>(c);
        }
    });
    for(auto& thread:threads) thread.join();
    std::printf("{\"schema\":1,\"simd_width\":%u,\"cases\":%zu}\n",unsigned(kSIMDSize),rows.size());
    for(size_t i=0;i<rows.size();++i) {
        const auto& row=rows[i]; const auto c=row.c;
        std::printf("{\"id\":%zu,\"dims\":%u,\"depth\":%u,\"total\":%u,\"seed\":%u,\"purpose\":%u,\"pseudo\":%s,\"sequence_hash\":%u",
                    i,c.dims,c.depth,c.total,c.seed,c.purpose,c.pseudo?"true":"false",row.hash);
        values("baseline",row.baseline);values("chunked",row.chunked);
        values("reordered",row.reordered);values("naive_resume",row.naive);std::printf("}\n");
    }
    return 0;
}
