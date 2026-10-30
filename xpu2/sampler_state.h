// Experimental XPU2 state envelope for the six-word integrator test signature.
// Not a dump of a C++ object and not a general MoonRay path-state format.
#pragma once
#include <moonray/rendering/pbr/sampler/IntegratorSample.h>
#include <array>
#include <cstdint>
#include <stdexcept>
#include <vector>
namespace xpu2 {
struct SamplerState {
    std::array<uint32_t,6> sequence;
    uint32_t dimensions,depth,total,next,pseudo;
    void validate() const {
        if(dimensions<1 || dimensions>3 || pseudo>1 || total==0 ||
           (total!=0xffffffffu && next>total) || next>0xffffffffu-8u)
            throw std::invalid_argument("Invalid sampler state");
    }
    moonray::pbr::SequenceID sid() const {
        return moonray::pbr::SequenceID(sequence[0],sequence[1],sequence[2],
                                       sequence[3],sequence[4],sequence[5]);
    }
};
inline uint32_t checksum(const std::vector<uint8_t>& bytes,size_t count) {
    uint32_t hash=2166136261u;
    for(size_t i=0;i<count;++i) hash=(hash^bytes[i])*16777619u;
    return hash; // Accidental corruption detection, not authentication.
}
inline std::vector<uint8_t> encode(const SamplerState& state) {
    state.validate();
    std::vector<uint8_t> bytes;
    auto put=[&](uint32_t word){for(unsigned shift=0;shift<32;shift+=8) bytes.push_back(uint8_t(word>>shift));};
    put(0x32555058u);put(1);put(state.dimensions);put(state.depth);put(state.total);
    put(state.next);put(state.pseudo);put(6);
    for(auto word:state.sequence) put(word);
    put(checksum(bytes,bytes.size()));
    return bytes;
}
inline SamplerState decode(const std::vector<uint8_t>& bytes) {
    if(bytes.size()!=60) throw std::invalid_argument("Incomplete sampler envelope");
    auto get=[&](unsigned index){
        uint32_t word=0; for(unsigned i=0;i<4;++i) word|=uint32_t(bytes[index*4+i])<<(i*8);
        return word;
    };
    if(get(0)!=0x32555058u || get(1)!=1 || get(7)!=6 || get(14)!=checksum(bytes,56))
        throw std::invalid_argument("Unsupported or corrupt sampler envelope");
    SamplerState state{{get(8),get(9),get(10),get(11),get(12),get(13)},
                       get(2),get(3),get(4),get(5),get(6)};
    state.validate();
    return state;
}
template<unsigned D>
class SamplerCursor {
    SamplerState state;
    moonray::pbr::IntegratorSample<D> sampler;
    static SamplerState checked(SamplerState input) {
        input.validate();
        if(input.dimensions!=D) throw std::invalid_argument("Sampler dimension mismatch");
        return input;
    }
public:
    explicit SamplerCursor(SamplerState input)
      :state(checked(input)),sampler(state.sid(),state.total,state.next) {
        sampler.setUsePseudoRandom(state.pseudo!=0);
    }
    std::array<float,D> draw() {
        if((state.total!=0xffffffffu && state.next>=state.total) || state.next>=0xffffffffu-8u)
            throw std::out_of_range("Sampler exhausted");
        std::array<float,D> values;
        sampler.getSample(values.data(),state.depth);
        state.next=sampler.getSampleNumber();
        return values;
    }
    SamplerState snapshot() const { return state; }
};
}
