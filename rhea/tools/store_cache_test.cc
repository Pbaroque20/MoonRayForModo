// The radiance cache on disk (rhea/object_warp.h ObjectStore::save / load, file form 3): a store's cells written and read
// back with the records beside them, its view-dependent light (Extra) and the sparse cache's slopes (Grad), each cell
// found again by its key with the same bytes. Built by rhea/tools/build_store_cache_test.py; prints JSON lines, exits
// non-zero on a failed check.
#include "object_warp.h"

#include <cstdio>
#include <cstring>

namespace rhea {
struct StoreTest {
    static int run() {
        int failed = 0;
        auto check = [&](const char* name, bool ok) {
            std::printf("{\"check\": \"%s\", \"ok\": %s}\n", name, ok ? "true" : "false");
            if (!ok) ++failed;
        };
        ObjectStore a;
        a.op.sparse = true, a.op.byObject = true;
        const int n = 300;
        for (int k = 0; k < n; ++k) {
            surface::V3 p{float(k) * 0.37f, float(k % 17) * 0.21f, float(k % 5) * 1.3f};
            auto& e = a.light.slot(p, k % 4, k % 6, std::uint32_t(k % 3));
            for (int q = 0; q < ObjectStore::NB; ++q) e.v[q] = float(k * 10 + q) * 0.125f;
            const size_t at = a.light.last;
            for (int q = 0; q < ObjectStore::NV - ObjectStore::NB; ++q) a.light.more(at).v[q] = float(k + q) * 0.5f;
            for (int q = 0; q < 18; ++q) a.light.slope(at).s[q] = float(k) * 0.01f + float(q);
            if (k % 7 == 0) {
                auto& f = a.fine.slot(p, (k % 4) - 1, k % 6, std::uint32_t(k % 3));
                for (int q = 0; q < ObjectStore::NB; ++q) f.v[q] = float(k + q);
            }
        }
        std::FILE* f = std::tmpfile();
        check("saved", f && a.save(f));
        if (!f) return 1;
        std::rewind(f);
        ObjectStore b;
        b.op = a.op;
        check("loaded", b.load(f));
        std::fclose(f);
        check("same cell counts", b.light.used == a.light.used && b.fine.used == a.fine.used);
        check("extras and slopes kept", b.light.extras.size() == b.light.slots.size() && b.light.grads.size() == b.light.slots.size());
        check("no slopes made for the albedo table", b.fine.grads.empty() && b.fine.extras.empty());
        bool same = true;
        for (const ObjectStore::Table* t : {&a.light, &a.fine})
            for (size_t i = 0; i < t->slots.size(); ++i) {
                const auto& e = t->slots[i];
                if (!e.full) continue;
                const ObjectStore::Table& u = t == &a.light ? b.light : b.fine;
                const auto* g = u.find(e.x, e.y, e.z, e.level, e.bin, e.obj);
                if (!g || std::memcmp(g->v, e.v, sizeof e.v) != 0) {
                    same = false;
                    continue;
                }
                const size_t j = size_t(g - u.slots.data());
                if (t == &a.light && (std::memcmp(&u.extras[j], &t->extras[i], sizeof t->extras[i]) != 0 ||
                                      std::memcmp(&u.grads[j], &t->grads[i], sizeof t->grads[i]) != 0))
                    same = false;
            }
        check("every cell back with its sums, extras and slopes", same);
        // A store that never learned slopes (sparse off) is written without them, and reads back without them.
        ObjectStore c;
        surface::V3 p{1, 2, 3};
        c.light.slot(p, 0, 0, 0).v[ObjectStore::VW] = 1;
        std::FILE* g = std::tmpfile();
        check("dense saved", g && c.save(g));
        if (!g) return 1;
        std::rewind(g);
        ObjectStore d;
        check("dense loaded", d.load(g));
        std::fclose(g);
        check("dense has no slopes", d.light.grads.empty() && d.light.used == 1);
        return failed;
    }
};
}  // namespace rhea

int main() { return rhea::StoreTest::run() ? 1 : 0; }
