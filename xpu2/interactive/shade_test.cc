// Private XPU2 shading library checks on the CPU (no renderer, no MoonRay
// binary): every lobe's sample() must agree with its eval() at the sampled
// direction, its pdf must integrate to at most one, and the two estimates of
// its albedo (importance-sampled and uniform-sphere) must agree. These are the
// properties MoonRay's own lobes have; a porting error breaks one of them.
//
// shade_test [samples]   prints one line per case and exits 1 on a failure.
#include "shade_builder.h"
#include <cstdio>
#include <cstdlib>
#include <random>
#include <string>
#include <vector>

using namespace xpu2::interactive;
using namespace xpu2::interactive::shade;

namespace {
struct Rng {
    std::mt19937_64 g{12345};
    std::uniform_real_distribution<float> u{0.0f, 0.99999994f};
    float operator()() { return u(g); }
};
struct Case {
    std::string name;
    Bsdf bsdf;
    bool mirror = false, spherical = false;
};
State testState(V3 wo) {
    State s;
    s.P = {0, 0, 0};
    s.Ng = s.N = {0, 0, 1};
    s.dPds = {1, 0, 0};
    s.dPdt = {0, 1, 0};
    s.wo = wo;
    return s;
}
Slice slice(V3 wo, bool entering = true) { return Slice{{0, 0, 1}, wo, AllLobeTypes, StfOff, true, entering}; }

int failures = 0;
void check(bool ok, const std::string& what) {
    if (!ok) {
        ++failures;
        std::printf("  FAIL %s\n", what.c_str());
    }
}
// One lobe record, all its directions.
// A lobe whose sampling passes totally internally reflected directions through (UnderClearcoat,
// as MoonRay's): its samples there differ from its evaluation by design.
bool passesTIR(const Bsdf& b, U32 record) {
    for (; record != NoIndex; record = b.records[record].child)
        if (b.records[record].kind == KindUnderClearcoat && b.records[record].under.passThroughTIR) return true;
    return false;
}
void testLobe(const std::string& name, const Bsdf& b, U32 record, V3 wo, int n, Rng& rng) {
    const Slice s = slice(wo);
    const Lobe& top = b.records[record];
    const bool mirror = (top.type & Mirror) != 0, tir = passesTIR(b, record);
    double sampled[3] = {0, 0, 0}, uniform[3] = {0, 0, 0}, pdfIntegral = 0;
    double sampled2[3] = {0, 0, 0}, uniform2[3] = {0, 0, 0}, pdf2 = 0;
    int mismatches = 0, nonfinite = 0, valid = 0;
    float worst = 0;
    for (int i = 0; i < n; ++i) {
        V3 wi;
        float pdf;
        const Color f = lobeSample(b, record, s, rng(), rng(), wi, pdf);
        if (!finite3(f) || !(pdf == pdf)) {
            ++nonfinite;
            continue;
        }
        if (pdf > 0 && !isExactlyZero(f)) {
            ++valid;
            const double e[3] = {f.x / pdf, f.y / pdf, f.z / pdf};
            for (int k = 0; k < 3; ++k) {
                sampled[k] += e[k];
                sampled2[k] += e[k] * e[k];
            }
            if (!mirror && !tir) {
                float pdf2;
                const Color f2 = lobeEval(b, record, s, wi, pdf2);
                const float df = maxComponent(cmax(f - f2, f2 - f)) / fmaxf(1e-4f, maxComponent(f));
                const float dp = fabsf(pdf - pdf2) / fmaxf(1e-4f, pdf);
                if (df > 2e-3f || dp > 2e-3f) {
                    ++mismatches;
                    worst = fmaxf(worst, fmaxf(df, dp));
                }
            }
        }
        if (!mirror) {
            const V3 u = sampleSphereUniform(rng(), rng());
            float up;
            const Color fu = lobeEval(b, record, s, u, up);
            if (finite3(fu) && up == up) {
                const double e[3] = {fu.x * FourPi, fu.y * FourPi, fu.z * FourPi};
                for (int k = 0; k < 3; ++k) {
                    uniform[k] += e[k];
                    uniform2[k] += e[k] * e[k];
                }
                pdfIntegral += up * FourPi;
                pdf2 += double(up * FourPi) * (up * FourPi);
            } else {
                ++nonfinite;
            }
        }
    }
    // Standard errors of the means.
    double seS[3], seU[3];
    for (int c = 0; c < 3; ++c) {
        sampled[c] /= n;
        uniform[c] /= n;
        seS[c] = sqrt(fmax(0.0, sampled2[c] / n - sampled[c] * sampled[c]) / n);
        seU[c] = sqrt(fmax(0.0, uniform2[c] / n - uniform[c] * uniform[c]) / n);
    }
    pdfIntegral /= n;
    const double sePdf = sqrt(fmax(0.0, pdf2 / n - pdfIntegral * pdfIntegral) / n);
    std::printf("%-34s wo.z %.2f valid %5.1f%% albedo %.4f %.4f %.4f", name.c_str(), wo.z, 100.0 * valid / n, sampled[0],
                sampled[1], sampled[2]);
    if (!mirror && !tir) std::printf(" (uniform %.4f %.4f %.4f) pdf integral %.4f", uniform[0], uniform[1], uniform[2], pdfIntegral);
    std::printf("\n");
    check(nonfinite == 0, name + ": non-finite values " + std::to_string(nonfinite));
    check(mismatches <= n / 1000, name + ": sample/eval mismatches " + std::to_string(mismatches) + " worst " + std::to_string(worst));
    if (!mirror && !tir) {
        check(pdfIntegral <= 1.01 + 5 * sePdf, name + ": pdf integrates past one " + std::to_string(pdfIntegral) + " (se " +
                                                   std::to_string(sePdf) + ")");
        // The two albedo estimates agree (within their errors) where the lobe's sampling covers its support.
        for (int c = 0; c < 3; ++c) {
            const double tol = 0.01 + 0.02 * fmax(sampled[c], uniform[c]) + 5 * sqrt(seS[c] * seS[c] + seU[c] * seU[c]);
            check(fabs(sampled[c] - uniform[c]) <= tol || pdfIntegral < 0.9,
                  name + ": albedo estimates disagree " + std::to_string(sampled[c]) + " vs " + std::to_string(uniform[c]) + " (tol " +
                      std::to_string(tol) + ")");
        }
    }
}
}  // namespace

int main(int argc, char** argv) {
    const int n = argc > 1 ? std::atoi(argv[1]) : 400000;
    Rng rng;
    const V3 N{0, 0, 1}, T{1, 0, 0};
    const V3 wos[] = {normalize(V3{0.2f, 0.1f, 0.97f}), normalize(V3{0.6f, -0.3f, 0.5f}), normalize(V3{0.9f, 0.2f, 0.12f})};
    for (V3 wo : wos) {
        const State st = testState(wo);
        auto run = [&](const char* name, auto build) {
            Bsdf b;
            Builder me(b, st);
            build(me);
            for (U32 i = 0; i < b.topCount; ++i)
                testLobe(std::string(name) + "#" + std::to_string(i), b, b.top[i], wo, n, rng);
        };
        run("lambert", [&](Builder& me) { addLambertianBRDF(me, {N, rgb(0.8f, 0.5f, 0.2f), nullptr}, 1.0f, Physical, 0); });
        run("lambert-transmission", [&](Builder& me) { addLambertianBTDF(me, {-N, rgb(0.6f)}, 1.0f, Physical, 0); });
        run("oren-nayar", [&](Builder& me) { addOrenNayarBRDF(me, {N, rgb(0.7f), 0.6f, nullptr}, 1.0f, Physical, 0); });
        for (float r : {0.1f, 0.4f, 0.8f}) {
            const std::string rs = std::to_string(r).substr(0, 3);
            run(("ggx-dielectric-" + rs).c_str(), [&](Builder& me) {
                addMicrofacetIsotropicBRDF(me, microfacetDielectric(N, 1.5f, r, GGXDistribution), 1.0f, Physical, 0);
            });
            run(("beckmann-conductor-" + rs).c_str(), [&](Builder& me) {
                addMicrofacetIsotropicBRDF(me, microfacetConductor(N, rgb(0.9f, 0.6f, 0.3f), rgb(1.0f), r, Beckmann), 1.0f, Physical, 0);
            });
            run(("ggx-conductor-" + rs).c_str(), [&](Builder& me) {
                addMicrofacetIsotropicBRDF(me, microfacetConductor(N, rgb(0.9f, 0.6f, 0.3f), rgb(1.0f), r, GGXDistribution), 1.0f, Physical, 0);
            });
            run(("aniso-" + rs).c_str(), [&](Builder& me) {
                addMicrofacetAnisotropicBRDF(me, microfacetAnisoConductor(N, rgb(0.9f), rgb(1.0f), r, r * 0.5f + 0.05f, T, Beckmann), 1.0f,
                                             Physical, 0);
            });
            run(("glass-bsdf-" + rs).c_str(), [&](Builder& me) {
                addMicrofacetIsotropicBSDF(me, {N, 1.5f, r, r, false, rgb(1), 0.0f, 1.5f, 1.0f, 1.0f, Beckmann, nullptr}, 1.0f, Physical, 0, 0);
            });
            run(("fabric-" + rs).c_str(), [&](Builder& me) {
                addFabricBRDF(me, {N, T, r, V3{0, 1, 0}, 10.0f, rgb(0.8f), nullptr}, 1.0f, Physical, 0);
            });
            run(("velvet-" + rs).c_str(), [&](Builder& me) { addVelvetBRDF(me, {N, r, rgb(0.8f), false, nullptr}, 1.0f, Physical, 0); });
            run(("clearcoat-over-lambert-" + rs).c_str(), [&](Builder& me) {
                addMicrofacetIsotropicClearcoat(me, {N, 1.5f, r, 0.2f, rgb(0.6f, 0.8f, 1.0f), true, GGXDistribution, nullptr}, 1.0f, Physical, 0);
                addLambertianBRDF(me, {N, rgb(0.8f), nullptr}, 1.0f, Physical, 0);
            });
            run(("specular-over-lambert-" + rs).c_str(), [&](Builder& me) {
                addMicrofacetIsotropicBRDF(me, microfacetDielectric(N, 1.5f, r, GGXDistribution), 1.0f, Physical, 0);
                addLambertianBRDF(me, {N, rgb(0.8f), nullptr}, 1.0f, Physical, 0);
            });
        }
        run("mirror", [&](Builder& me) { addMirrorBRDF(me, mirrorConductor(N, rgb(0.9f), rgb(1.0f)), 1.0f, Physical, 0); });
        run("mirror-glass", [&](Builder& me) {
            addMirrorBSDF(me, {N, 1.5f, rgb(1), 0.0f, 1.5f, 1.0f, 1.0f, nullptr}, 1.0f, Physical, 0, 0);
        });
        run("eye-caustic", [&](Builder& me) {
            addEyeCausticBRDF(me, {N, normalize(V3{0.1f, 0.0f, 1.0f}), rgb(1), 50.0f, rgb(1)}, 1.0f, Physical, 0);
        });
        Iridescence iri{N, 1.0f, 0, rgb(1, 0, 0), rgb(0, 0, 1), false, ColorRamp{}, 1.0f, 1.0f, 1.0f, 1.0f};
        run("iridescent-ggx", [&](Builder& me) {
            addMicrofacetIsotropicBRDF(me, microfacetDielectric(N, 1.5f, 0.4f, GGXDistribution, &iri), 1.0f, Physical, 0);
        });
    }
    std::printf("%s (%d failures)\n", failures ? "FAILED" : "passed", failures);
    return failures ? 1 : 0;
}
