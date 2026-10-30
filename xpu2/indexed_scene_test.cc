// Native scene-index contracts. Prepared bytes are synthetic, not native BVHs.
#include "indexed_scene.h"
#include <atomic>
#include <chrono>
#include <iostream>
using namespace xpu2::indexed;
static unsigned checks = 0;
static void check(bool ok, const char* message) {
    ++checks; if (!ok) throw std::runtime_error(message);
}
template<class F> static void rejects(F f) {
    bool rejected = false;
    try { f(); } catch (const std::exception&) { rejected = true; }
    check(rejected, "Invalid transaction accepted");
}
static Edit edit(std::string id, Kind kind, Field field, Bytes value,
                 std::optional<std::set<std::string>> deps = {}) {
    return {std::move(id), kind, {{field, std::move(value)}}, std::move(deps), {}};
}
int main() {
 try {
    SceneIndex index;
    unsigned calls = 0;
    auto encode = [&](Kind, Field, const Bytes& bytes) { ++calls; return bytes; };
    auto empty = index.acquire();
    auto initial = index.prepare(empty, {
        edit("geometry", Kind::Geometry, Field::Positions, {1,2,3}),
        edit("texture", Kind::Texture, Field::Pixels, {4,5,6}),
        edit("material", Kind::Material, Field::Shading, {7}, {{"texture"}}),
        edit("object", Kind::Instance, Field::Transform, {8}, {{"geometry","material"}}),
        edit("light", Kind::Light, Field::Parameters, {9}),
        edit("camera", Kind::Camera, Field::Transform, {10})}, {}, encode);
    check(index.acquire() == empty && calls == 6, "Prepare published early");
    auto first = initial.view();
    check(index.commit(initial) && index.current(first), "Initial commit failed");
    check(first->kinds.at(Kind::Geometry) == std::set<std::string>{"geometry"} &&
          first->kinds.at(Kind::Instance) == std::set<std::string>{"object"}, "Kind classification");
    check(first->edgeCount == 3 && first->residentBytes == 20, "Initial budget accounting");
    auto geometry = first->entities.at("geometry")->buffers.at(Field::Positions);
    auto transform = first->entities.at("object")->buffers.at(Field::Transform);
    auto unchanged = index.prepare(first, {edit("texture", Kind::Texture, Field::Pixels, {4,5,6})}, {}, encode);
    check(unchanged.view() == first && calls == 6, "No-op encoded resources");
    check(index.commit(unchanged), "No-op commit failed");
    auto moved = index.prepare(first, {edit("object", Kind::Instance, Field::Transform, {11})}, {}, encode);
    check(moved.view()->changes.preparedBuffers == 1 && calls == 7, "Transform rebuilt mesh");
    check(moved.view()->entities.at("geometry") == first->entities.at("geometry"), "Untouched entity not shared");
    check(index.commit(moved), "Transform commit");
    check(!index.commit(initial) && !index.commit(unchanged), "Stale candidate accepted");
    rejects([&]{ index.prepare(first, {}, {}, encode); });
    auto before = index.acquire();
    auto painted = index.prepare(before, {edit("texture", Kind::Texture, Field::Pixels, {12})}, {}, encode);
    auto after = painted.view();
    check(after->changes.affected == std::set<std::string>{"texture","material","object"}, "Dependency invalidation");
    check(after->changes.preparedBuffers == 1, "Dependency edit re-encoded consumers");
    check(after->entities.at("geometry")->buffers.at(Field::Positions) == geometry, "Geometry buffer changed");
    check(after->entities.at("material")->buffers == before->entities.at("material")->buffers, "Material parameters re-encoded");
    check(after->entities.at("light") == first->entities.at("light"), "Unrelated light invalidated");
    check(index.commit(painted), "Texture commit");
    check(first->entities.at("object")->buffers.at(Field::Transform) == transform && transform->source == Bytes{8}, "Old reader changed");
    auto active = index.acquire();
    unsigned beforeFailure = calls;
    rejects([&]{index.prepare(active, {edit("bad",Kind::Material,Field::Shading,{1},{{"missing"}})}, {}, encode);});
    rejects([&]{index.prepare(active, {}, {"texture"}, encode);});
    rejects([&]{index.prepare(active, {}, {"missing"}, encode);});
    rejects([&]{index.prepare(active, {edit("light",Kind::Camera,Field::Transform,{1})}, {}, encode);});
    rejects([&]{index.prepare(active, {edit("light",Kind::Light,Field::Parameters,{1}),edit("light",Kind::Light,Field::Parameters,{2})}, {}, encode);});
    check(calls == beforeFailure && index.current(active), "Validation changed active scene or encoded data");
    rejects([&]{index.prepare(active, {edit("texture",Kind::Texture,Field::Pixels,{13})}, {},
        [](Kind,Field,const Bytes&) -> Bytes { throw std::runtime_error("backend failed"); });});
    check(index.current(active), "Encoding failure published candidate");
    SceneIndex foreign;
    check(!foreign.commit(painted), "Foreign candidate accepted");
    auto disconnected = index.prepare(active, {{"material",Kind::Material,{},std::set<std::string>{},{}}}, {"texture"}, encode);
    check(disconnected.view()->changes.affected == std::set<std::string>{"material","object"}, "Unbinding invalidation");
    check(index.commit(disconnected) && !index.acquire()->entities.count("texture"), "Atomic detach/remove");
    check(!index.acquire()->kinds.count(Kind::Texture), "Removed kind membership retained");
    check(index.acquire()->edgeCount == 2 && index.acquire()->residentBytes == 14, "Removal budget accounting");
    auto recreated = index.prepare(index.acquire(), {edit("texture",Kind::Texture,Field::Pixels,{4,5,6})}, {}, encode);
    check(recreated.view()->entities.at("texture")->revision > first->entities.at("texture")->revision, "Reused identity ABA");
    check(index.commit(recreated), "Recreate failed");
    auto cycled = index.prepare(index.acquire(), {
        {"material",Kind::Material,{},std::set<std::string>{"texture"},{}},
        {"texture",Kind::Texture,{},std::set<std::string>{"material"},{}}}, {}, encode);
    check(cycled.view()->changes.affected == std::set<std::string>{"material","texture","object"}, "Cycle invalidation");
    check(index.commit(cycled), "Cycle commit");
    auto erased = index.prepare(index.acquire(), {{"object",Kind::Instance,{}, {}, {Field::Transform}}}, {}, encode);
    check(erased.view()->entities.at("object")->buffers.empty() && erased.view()->changes.preparedBuffers == 0, "Field erase");
    // Worker reads retained immutable data; coordinator-only operations fail.
    std::atomic<unsigned> reads{0}, denied{0};
    std::vector<std::thread> workers;
    for (unsigned i=0; i<8; ++i) workers.emplace_back([&, first] {
        for (unsigned j=0;j<10000;++j)
            if (first->entities.at("geometry")->buffers.at(Field::Positions)->source == Bytes{1,2,3}) ++reads;
        try { index.acquire(); } catch (const std::logic_error&) { ++denied; }
    });
    check(index.commit(erased), "Publish during reader activity");
    for (auto& worker : workers) worker.join();
    check(reads == 80000 && denied == 8, "Concurrent immutable readers");
    SceneIndex bounded({2,2,8});
    auto b = bounded.acquire();
    rejects([&]{bounded.prepare(b, {edit("large",Kind::Geometry,Field::Positions,Bytes(9))}, {}, encode);});
    rejects([&]{bounded.prepare(b, {edit("large",Kind::Geometry,Field::Positions,Bytes(5))}, {}, encode);});
    rejects([&]{bounded.prepare(b, {edit("a",Kind::Material,Field::Shading,{1})}, {},
        [](Kind,Field,const Bytes&){return Bytes(8);});});
    check(bounded.current(b), "Budget failure changed scene");
    SceneIndex edgeLimit({4,1,100});
    rejects([&]{edgeLimit.prepare(edgeLimit.acquire(), {
        edit("a",Kind::Material,Field::Shading,{1},{{"b","c"}}),
        edit("b",Kind::Texture,Field::Pixels,{2}),edit("c",Kind::Texture,Field::Pixels,{3})}, {}, encode);});
    // Structural sharing over a larger synthetic index. No renderer speed claim.
    SceneIndex many;
    std::vector<Edit> objects;
    objects.push_back(edit("shared",Kind::Geometry,Field::Positions,Bytes(1024*1024,42)));
    for (unsigned i=0;i<10000;++i) objects.push_back(edit("instance"+std::to_string(i),Kind::Instance,Field::Transform,{0},{{"shared"}}));
    auto large = many.prepare(many.acquire(),objects,{},encode);
    check(many.commit(large), "Large index commit");
    auto begun = std::chrono::steady_clock::now();
    auto update = many.prepare(many.acquire(), {edit("instance5000",Kind::Instance,Field::Transform,{1})}, {}, encode);
    auto microseconds = std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now()-begun).count();
    check(update.view()->changes.affected.size()==1 && update.view()->changes.preparedBytes==1 && update.view()->changes.preparedBuffers==1, "Large transform copied geometry");
    check(update.view()->entities.at("shared")==large.view()->entities.at("shared"), "Large shared geometry replaced");
    check(many.commit(update), "Large transform publication");
    auto deformed = many.prepare(many.acquire(), {edit("shared",Kind::Geometry,Field::Positions,{43})}, {}, encode);
    check(deformed.view()->changes.affected.size()==10001 && deformed.view()->changes.preparedBuffers==1,
          "Shared geometry did not invalidate all instances once");
    check(deformed.view()->residentBytes==20002 &&
          deformed.view()->entities.at("instance5001")->buffers==large.view()->entities.at("instance5001")->buffers,
          "Shared geometry update rebuilt instance buffers or miscounted bytes");
    std::cout << "{\"transform_prepare_microseconds\":" << microseconds << ",\"passed\":true,\"checks\":" << checks << ",\"reader_accesses\":" << reads
              << ",\"large_entities\":10001,\"transform_prepared_buffers\":1,\"transform_prepared_bytes\":1}\n";
    return 0;
 } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
