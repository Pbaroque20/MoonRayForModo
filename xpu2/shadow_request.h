// Owned numeric surface-visibility request. No arena handles or native pointers.
#pragma once
#include <cmath>
#include <cstdint>
#include <type_traits>
#include <vector>
#include <utility>
namespace xpu2 {
struct ShadowRequest {
    uint64_t scene, revision, request;
    uint32_t light;
    int32_t mask, receiver;
    float origin[3], direction[3], nearT, farT, time;
};
static_assert(std::is_trivially_copyable<ShadowRequest>::value, "Numeric request required");
inline bool validShadow(const ShadowRequest& q) {
    if (!q.scene || !q.revision || !q.request || !q.mask ||
        !std::isfinite(q.nearT) || !std::isfinite(q.farT) ||
        !std::isfinite(q.time) || q.nearT < 0 || q.farT < q.nearT) return false;
    bool nonzero=false;
    for (int i=0;i<3;++i) {
        if (!std::isfinite(q.origin[i]) || !std::isfinite(q.direction[i])) return false;
        nonzero |= q.direction[i]!=0;
    }
    return nonzero;
}
// Host-only BORROWED scene bindings. Caller must hold the native scene alive and
// immutable until queries finish. This table does not extend native scene lifetime.
// Scene/revision identities must never be reused while outstanding work exists.
class ShadowBindings {
    uint64_t scene_,revision_;
    std::vector<uint64_t> lights_;
public:
    ShadowBindings(uint64_t scene,uint64_t revision,std::vector<uint64_t> lights)
      :scene_(scene),revision_(revision),lights_(std::move(lights)) {}
    bool resolve(const ShadowRequest& q,uint64_t& nativeLight) const {
        nativeLight=0;
        if (!validShadow(q) || q.scene!=scene_ || q.revision!=revision_ ||
            q.light>=lights_.size() || !lights_[q.light]) return false;
        nativeLight=lights_[q.light];return true;
    }
};
}
