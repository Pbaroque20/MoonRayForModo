// XPU2 diagnostic cache-aware continuation, using unchanged native samplers.
#pragma once
#include "sampler_state.h"
namespace xpu2 {
static_assert(moonray::pbr::kSIMDSize == 8, "Window envelope requires AVX8 native sampler");
struct WindowState {
    SamplerState sampler;
    uint32_t cacheBegin;
    void validate() const {
        sampler.validate();
        if(cacheBegin>sampler.next || sampler.next-cacheBegin>8)
            throw std::invalid_argument("Invalid sampler cache window");
    }
};
inline std::vector<uint8_t> encodeWindow(const WindowState& state) {
    state.validate();
    auto bytes=encode(state.sampler);
    bytes.resize(56);bytes[4]=2; // Distinct version; v1 decoders must reject it.
    auto put=[&](uint32_t v){for(unsigned i=0;i<4;++i)bytes.push_back(uint8_t(v>>(8*i)));};
    put(state.cacheBegin);put(checksum(bytes,60));
    return bytes;
}
inline WindowState decodeWindow(const std::vector<uint8_t>& bytes) {
    if(bytes.size()!=64)throw std::invalid_argument("Incomplete window envelope");
    auto get=[&](unsigned word){
        uint32_t v=0;for(unsigned i=0;i<4;++i)v|=uint32_t(bytes[word*4+i])<<(8*i);return v;
    };
    if(get(1)!=2 || get(15)!=checksum(bytes,60))
        throw std::invalid_argument("Unsupported/corrupt window envelope");
    auto base=bytes;base.resize(56);base[4]=1;
    auto h=checksum(base,56);
    for(unsigned i=0;i<4;++i)base.push_back(uint8_t(h>>(8*i)));
    WindowState state{decode(base),get(14)};
    state.validate();return state;
}
template<unsigned D>
class WindowCursor {
    WindowState state;
    moonray::pbr::IntegratorSample<D> sampler;
    static WindowState checked(WindowState s) {
        s.validate();
        if(s.sampler.dimensions!=D)throw std::invalid_argument("Wrong window dimensions");
        return s;
    }
public:
    explicit WindowCursor(WindowState input)
      :state(checked(input)),sampler(state.sampler.sid(),state.sampler.total,state.cacheBegin) {
        sampler.setUsePseudoRandom(state.sampler.pseudo!=0);
        // Rebuild the same cached window through the public API. This is a
        // diagnostic strategy, not a proposed GPU performance implementation.
        for(uint32_t i=state.cacheBegin;i<state.sampler.next;++i) {
            float ignored[D];sampler.getSample(ignored,state.sampler.depth);
        }
    }
    std::array<float,D> draw() {
        if((state.sampler.total!=0xffffffffu && state.sampler.next>=state.sampler.total)
           || state.sampler.next>=0xffffffffu-8u)throw std::out_of_range("Window exhausted");
        if(state.sampler.next-state.cacheBegin==8)state.cacheBegin=state.sampler.next;
        std::array<float,D> value;sampler.getSample(value.data(),state.sampler.depth);
        state.sampler.next=sampler.getSampleNumber();return value;
    }
    WindowState snapshot() const {return state;}
};
}
