// Cryptomatte as MoonRay's vector mode keeps it (pbr/core/Cryptomatte.cc, ShadeBundleHandler, Film's bundled radiance
// handler), with the kit's Modo patches: categories (cryptomatte_id_channel 1 and 2 read modo_material_id and
// modo_asset_id) and P0.
//
// A sample records events: its camera-depth hit (coverage once, the path's radiance as beauty), and along presence
// each partly present surface (its share of coverage with its presence as alpha) and the surface its continuation
// reaches, whose radiance comes as beauty alone over the path pixel weight. The film merges each event into its
// pixel's fragment of the same ID (and presence depth, cryptomatte_multi_presence), in every category; written
// files sort fragments by coverage, normalize it over the pixel's samples and average their data over the
// fragment's samples. Vector mode records no reflected or refracted Cryptomatte: those blocks stay empty.
#pragma once
#include "aov_state.h"
#if !defined(__CUDACC_RTC__)
#include <algorithm>
#include <vector>
#endif

namespace xpu2::interactive::aov {

// A path's Cryptomatte role (paths::Pending::crypto): an event of the sample (>= 0), none, the parent's (a path
// pushed this iteration), a camera ray not yet at a surface, or a presence continuation not yet at one.
constexpr int CryptoNone = -1, CryptoInherit = -2, CryptoCamera = -3, CryptoThrough = -4;
constexpr U32 CryptoMaxEvents = 40;
constexpr U32 CryptoNoDepth = 0xffffffffu;  // a path that is not a presence path (CryptomatteData::mPresenceDepth -1)

struct CryptoEvent {
    float id, materialId, assetId;
    float weight;      // the coverage it adds
    float beauty[4];   // the beauty it adds
    V3 position, p0, normal, refP, refN;
    float uv[2];
    U32 presenceDepth;
    U32 increment;     // one of the fragment's samples (its data averaged over them); else beauty alone
    float scale;       // the radiance credited to it is scaled by this (1 / path pixel weight)
    U32 radianceAlpha; // the credited radiance's alpha kept (a camera hit's), else dropped (presence paths)
    U32 credit;        // takes the radiance of its paths (a presence path's only above 0.01 of pixel weight)
    U32 used;          // reaches the film: a surface sample, or a path that brought radiance (its hit's alpha)
};

// The attributes Cryptomatte reads (Tables::crypto*): the deep ID, Modo's material and asset IDs, the UV (none: st).
X2_HD inline float cryptoFloat(const shade::State& st, U32 key) {
    float v[3];
    return key && shade::primValue(st, key, v) ? v[0] : 0.0f;
}
// shading::State::getRefN: ref_N, else the normal of ref_P's partials (across a curve with the view direction).
X2_HD inline V3 cryptoRefN(const shade::State& st) {
    using namespace shade;
    float v[3];
    if (primValue(st, primKey("ref_N", PrimVec3f), v)) return V3{v[0], v[1], v[2]};
    if (!primProvided(st, primKey("ref_P", PrimVec3f))) return V3{0, 0, 0};
    float ds[3] = {0, 0, 0}, dt[3] = {0, 0, 0};
    primPartials(st, primKey("ref_P", PrimVec3f), ds, dt);
    V3 a{ds[0], ds[1], ds[2]}, b{dt[0], dt[1], dt[2]};
    if (isZero(lengthSqr(a))) return V3{0, 0, 0};
    a = normalize(a);
    if (isZero(lengthSqr(b))) b = cross(a, cross(a, normalize(renderVector(st, st.wo))));
    const V3 n = cross(a, normalize(b));
    return isZero(lengthSqr(n)) ? V3{0, 0, 0} : n;
}
// A camera-depth hit's data (ShadeBundleHandler): IDs, render-space position and normal, ref_P, ref_N, P0 (MoonRay
// takes the world-to-render transform of its render-space p0) and the UV.
X2_HD inline void cryptoHit(const Tables& t, const shade::State& st, const float* worldToRender, CryptoEvent& e) {
    e.id = cryptoFloat(st, t.cryptoIdKey);
    e.materialId = cryptoFloat(st, shade::primKey("modo_material_id", shade::PrimFloat));
    e.assetId = cryptoFloat(st, shade::primKey("modo_asset_id", shade::PrimFloat));
    e.position = renderPointOf(worldToRender, st.P);
    e.normal = renderVectorOf(worldToRender, st.N);
    float v[3];
    e.refP = shade::primValue(st, shade::primKey("ref_P", shade::PrimVec3f), v) ? V3{v[0], v[1], v[2]} : V3{0, 0, 0};
    e.refN = cryptoRefN(st);
    e.p0 = renderPointOf(worldToRender, e.position);
    if (t.cryptoUvKey && shade::primValue(st, t.cryptoUvKey, v)) {
        e.uv[0] = v[0];
        e.uv[1] = v[1];
    } else {
        e.uv[0] = st.s;
        e.uv[1] = st.t;
    }
}

#ifndef __CUDACC__
// CryptomatteBuffer, a category each (0: the deep ID, 1: material, 2: asset).
class CryptoBuffer {
public:
    struct Fragment {
        float id, coverage;
        V3 position, p0, normal;
        float beauty[4];
        V3 refP, refN;
        float uv[2];
        U32 presenceDepth, samples;
    };
    void init(U32 width, U32 height, U32 categories, bool multiPresence) {
        width_ = width;
        multiPresence_ = multiPresence;
        categories_ = std::max<U32>(1, std::min<U32>(categories, 3));
        pixels_.assign(size_t(categories_) * width * height, {});
    }
    bool empty() const { return pixels_.empty(); }
    U32 categories() const { return categories_; }
    // A buffer of another's shape, empty; and one pixel's fragments copied from it (a checkpoint's copy, taken tile by
    // tile under the film's locks: HostFilm::snapshotCrypto).
    void like(const CryptoBuffer& o) {
        width_ = o.width_;
        multiPresence_ = o.multiPresence_;
        categories_ = o.categories_;
        pixels_.assign(o.pixels_.size(), {});
    }
    void copyPixel(const CryptoBuffer& o, size_t pixel) {
        const size_t n = pixels_.size() / categories_;
        for (U32 c = 0; c < categories_; ++c) pixels_[c * n + pixel] = o.pixels_[c * n + pixel];
    }
    // addSampleVector, in every category with its ID.
    void add(size_t pixel, const CryptoEvent& e) {
        if (pixels_.empty()) return;
        const size_t n = pixels_.size() / categories_;
        for (U32 c = 0; c < categories_; ++c) {
            const float id = c == 0 ? e.id : c == 1 ? e.materialId : e.assetId;
            std::vector<Fragment>& list = pixels_[c * n + pixel];
            Fragment* f = nullptr;
            for (Fragment& g : list)
                if (g.id == id && (!multiPresence_ || g.presenceDepth == e.presenceDepth)) {
                    f = &g;
                    break;
                }
            if (!f) {
                // A new fragment counts one sample, even one begun by beauty alone (whose data is zero).
                list.push_back(Fragment{id, 0.0f, {0, 0, 0}, {0, 0, 0}, {0, 0, 0}, {0, 0, 0, 0}, {0, 0, 0}, {0, 0, 0}, {0, 0}, e.presenceDepth, 0});
                f = &list.back();
                f->coverage = e.weight;
                f->position = e.position;
                f->p0 = e.p0;
                f->normal = e.normal;
                for (int k = 0; k < 4; ++k) f->beauty[k] = e.beauty[k];
                f->refP = e.refP;
                f->refN = e.refN;
                f->uv[0] = e.uv[0];
                f->uv[1] = e.uv[1];
                f->samples = 1;
                continue;
            }
            f->coverage += e.weight;
            if (e.increment) {
                f->position = surface::add(f->position, e.position);
                f->p0 = surface::add(f->p0, e.p0);
                f->normal = surface::add(f->normal, e.normal);
                f->refP = surface::add(f->refP, e.refP);
                f->refN = surface::add(f->refN, e.refN);
                f->uv[0] += e.uv[0];
                f->uv[1] += e.uv[1];
                ++f->samples;
            }
            for (int k = 0; k < 4; ++k) f->beauty[k] += e.beauty[k];
        }
    }
    // Another buffer's fragments (the GPU's, or another lane's) merged in.
    void merge(size_t pixel, U32 category, const Fragment& g) {
        const size_t n = pixels_.size() / categories_;
        std::vector<Fragment>& list = pixels_[category * n + pixel];
        for (Fragment& f : list)
            if (f.id == g.id && (!multiPresence_ || f.presenceDepth == g.presenceDepth)) {
                f.coverage += g.coverage;
                f.position = surface::add(f.position, g.position);
                f.p0 = surface::add(f.p0, g.p0);
                f.normal = surface::add(f.normal, g.normal);
                f.refP = surface::add(f.refP, g.refP);
                f.refN = surface::add(f.refN, g.refN);
                f.uv[0] += g.uv[0];
                f.uv[1] += g.uv[1];
                for (int k = 0; k < 4; ++k) f.beauty[k] += g.beauty[k];
                f.samples += g.samples;
                return;
            }
        list.push_back(g);
    }
    // finalize: by coverage, the larger first (ties by the larger ID), coverage over the pixel's samples, the data
    // over the fragment's.
    void finalize(const std::vector<U32>& counts) {
        const size_t n = pixels_.size() / categories_;
        for (U32 c = 0; c < categories_; ++c)
            for (size_t p = 0; p < n; ++p) {
                if (!counts[p]) continue;
                std::vector<Fragment>& list = pixels_[c * n + p];
                std::stable_sort(list.begin(), list.end(), [](const Fragment& a, const Fragment& b) {
                    return a.coverage != b.coverage ? a.coverage > b.coverage : a.id > b.id;
                });
                const float rn = 1.0f / float(counts[p]);
                for (Fragment& f : list) {
                    f.coverage *= rn;
                    if (!f.samples) continue;
                    const float r = 1.0f / float(f.samples);
                    f.position = surface::mul(f.position, r);
                    f.p0 = surface::mul(f.p0, r);
                    f.normal = surface::mul(f.normal, r);
                    for (int k = 0; k < 4; ++k) f.beauty[k] *= r;
                    f.refP = surface::mul(f.refP, r);
                    f.refN = surface::mul(f.refN, r);
                    f.uv[0] *= r;
                    f.uv[1] *= r;
                }
            }
    }
    const std::vector<Fragment>& fragments(U32 category, size_t pixel) const {
        static const std::vector<Fragment> none;
        if (pixels_.empty() || category >= categories_) return none;
        return pixels_[category * (pixels_.size() / categories_) + pixel];
    }
    U32 width() const { return width_; }

private:
    std::vector<std::vector<Fragment>> pixels_;
    U32 width_ = 0, categories_ = 1;
    bool multiPresence_ = false;
};
#endif

}  // namespace xpu2::interactive::aov
