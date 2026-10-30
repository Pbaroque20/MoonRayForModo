// Owned incremental scene resources for the isolated XPU2 coordinator.
// No Modo/native SceneContext pointers or device handles are stored here.
#pragma once
#include "persistent_map.h"
#include <algorithm>
#include <cstdint>
#include <deque>
#include <functional>
#include <limits>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

namespace xpu2::indexed {
using Bytes = std::vector<uint8_t>;
enum class Kind { Geometry, Instance, Material, Texture, Light, Environment, Camera, Volume, Attribute, Auxiliary };
enum class Field { Topology, Positions, Transform, Shading, Visibility, Pixels, Parameters };
inline bool valid(Kind k) { return k >= Kind::Geometry && k <= Kind::Auxiliary; }
inline bool valid(Field f) { return f >= Field::Topology && f <= Field::Parameters; }
struct Buffer {
    uint64_t revision;
    Bytes source, prepared;
    // Prepared as it came (SceneIndex::same): the source is what is prepared, held once.
    bool same = false;
    const Bytes& ready() const { return same ? source : prepared; }
};
struct Entity {
    Kind kind;
    uint64_t revision; // Changes on direct edits OR transitive invalidation.
    std::set<std::string> dependencies;
    std::map<Field, std::shared_ptr<const Buffer>> buffers;
};
struct Edit {
    std::string id;
    Kind kind;
    std::map<Field, Bytes> fields; // Only notified fields; absent means unchanged.
    std::optional<std::set<std::string>> dependencies;
    std::set<Field> erase;
};
struct Changes {
    std::set<std::string> direct, affected, removed;
    size_t preparedBuffers = 0, preparedBytes = 0;
};
struct Snapshot {
    uint64_t revision;
    PersistentMap<std::string, std::shared_ptr<const Entity>> entities;
    // Cached reverse edges: dependency -> consumers.
    PersistentMap<std::string, std::set<std::string>> consumers;
    PersistentMap<Kind, std::set<std::string>> kinds;
    Changes changes;
    size_t residentBytes, edgeCount;
};
using View = std::shared_ptr<const Snapshot>;
using Prepare = std::function<Bytes(Kind, Field, const Bytes&)>;
struct Limits {
    size_t entities = 1000000, edges = 4000000;
    size_t bytes = size_t(4) * 1024 * 1024 * 1024;
};
class SceneIndex {
public:
    class Candidate {
        friend class SceneIndex;
        std::shared_ptr<const int> owner;
        View base, next;
        Candidate(std::shared_ptr<const int> o, View b, View n)
            : owner(std::move(o)), base(std::move(b)), next(std::move(n)) {}
    public:
        View view() const { return next; }
        View baseView() const { return base; }
    };
    explicit SceneIndex(Limits limits = {}) : limits_(limits) {
        if (!limits.entities || !limits.edges || !limits.bytes)
            throw std::invalid_argument("Empty scene budget");
        active_ = std::make_shared<const Snapshot>(Snapshot{0, {}, {}, {}, {}, 0, 0});
    }
    SceneIndex(const SceneIndex&) = delete;
    SceneIndex& operator=(const SceneIndex&) = delete;
    View acquire() const { checkThread(); return active_; }
    bool current(const View& view) const { checkThread(); return view && view == active_; }

    // The preparer that keeps a resource as it came: its buffer holds it once (Buffer::ready), not twice.
    static Bytes same(Kind, Field, const Bytes&) { return {}; }
    // Two-phase publication: the native adapter must acknowledge candidate.view()
    // before commit. On rejection, discard candidate; active scene stays unchanged.
    // Prepare can encode owned CPU bytes. CUDA uploads/fences need a separate adapter.
    Candidate prepare(const View& base, const std::vector<Edit>& edits,
                      const std::set<std::string>& removed, const Prepare& encode) const {
        return prepare(base, std::vector<Edit>(edits), removed, encode);
    }
    // As above, the edits' bytes moved into the index rather than copied (a heavy scene's gigabyte of geometry).
    Candidate prepare(const View& base, std::vector<Edit>&& edits,
                      const std::set<std::string>& removed, const Prepare& encode) const {
        checkThread();
        if (!base || base != active_) throw std::invalid_argument("Stale scene base");
        if (!encode) throw std::invalid_argument("Missing resource preparer");
        const auto* target = encode.target<Bytes (*)(Kind, Field, const Bytes&)>();
        const bool identity = target && *target == &SceneIndex::same;
        if (base->revision == std::numeric_limits<uint64_t>::max())
            throw std::overflow_error("Scene revision exhausted");
        // Do not copy the previous transaction's potentially scene-sized change sets.
        auto next = std::make_shared<Snapshot>(Snapshot{base->revision + 1,
            base->entities, base->consumers, base->kinds, {}, base->residentBytes, base->edgeCount});
        next->changes.removed = removed;
        std::set<std::string> seen;
        // Validate all patches before expensive encoding.
        for (const auto& id : removed)
            if (!base->entities.count(id)) throw std::invalid_argument("Unknown removal");
        for (const auto& edit : edits) {
            if (edit.id.empty() || !seen.insert(edit.id).second || removed.count(edit.id) || !valid(edit.kind))
                throw std::invalid_argument("Invalid/duplicate entity edit");
            auto old = base->entities.find(edit.id);
            if (old != base->entities.end() && old->second->kind != edit.kind)
                throw std::invalid_argument("Entity kind cannot change in place");
            for (const auto& pair : edit.fields)
                if (!valid(pair.first) || edit.erase.count(pair.first) || pair.second.size() > limits_.bytes)
                    throw std::invalid_argument("Invalid resource patch");
            for (auto field : edit.erase)
                if (!valid(field)) throw std::invalid_argument("Invalid erased field");
        }
        if (base->entities.size() - removed.size() > limits_.entities)
            throw std::length_error("Entity budget exceeded");
        std::map<Kind, std::set<std::string>> changedKinds;
        auto members = [&](Kind kind) -> std::set<std::string>& {
            auto found = changedKinds.find(kind);
            if (found == changedKinds.end())
                found = changedKinds.emplace(kind, base->kinds.count(kind) ? base->kinds.at(kind) : std::set<std::string>{}).first;
            return found->second;
        };
        for (const auto& id : removed) {
            members(next->entities.at(id)->kind).erase(id);
            next->entities.erase(id);
        }
        // Build metadata and raw changes first. Encoding happens after graph validation.
        std::map<std::string, std::shared_ptr<Entity>> changed;
        std::map<std::string, std::set<Field>> dirty;
        for (auto& edit : edits) {
            auto old = base->entities.find(edit.id);
            bool created = old == base->entities.end();
            auto entity = created ? std::make_shared<Entity>(Entity{edit.kind, next->revision, {}, {}})
                                  : std::make_shared<Entity>(*old->second);
            bool different = created;
            if (edit.dependencies && *edit.dependencies != entity->dependencies) {
                entity->dependencies = *edit.dependencies;
                different = true;
            }
            for (auto field : edit.erase) different = entity->buffers.erase(field) != 0 || different;
            for (auto& [field, bytes] : edit.fields) {
                auto before = entity->buffers.find(field);
                if (before != entity->buffers.end() && before->second->source == bytes) continue;
                entity->buffers[field] = std::make_shared<const Buffer>(Buffer{next->revision, std::move(bytes), {}, identity});
                dirty[edit.id].insert(field);
                different = true;
            }
            if (different) {
                entity->revision = next->revision;
                next->entities.set(edit.id, entity);
                if (created) members(edit.kind).insert(edit.id);
                changed[edit.id] = entity;
                next->changes.direct.insert(edit.id);
            }
        }
        if (next->entities.size() > limits_.entities) throw std::length_error("Entity budget exceeded");
        if (next->changes.direct.empty() && removed.empty()) return Candidate(owner_, base, base);
        for (const auto& [kind, ids] : changedKinds) {
            if (ids.empty()) next->kinds.erase(kind);
            else next->kinds.set(kind, ids);
        }
        // Accumulate each reverse-set edit once, including bulk scene creation.
        std::map<std::string, std::set<std::string>> changedConsumers;
        auto consumersFor = [&](const std::string& id) -> std::set<std::string>& {
            auto found = changedConsumers.find(id);
            if (found == changedConsumers.end())
                found = changedConsumers.emplace(id, base->consumers.count(id) ? base->consumers.at(id) : std::set<std::string>{}).first;
            return found->second;
        };
        auto unlink = [&](const std::string& id) {
            auto old = base->entities.find(id);
            if (old == base->entities.end()) return;
            for (const auto& dependency : old->second->dependencies) {
                next->edgeCount -= consumersFor(dependency).erase(id);
            }
        };
        for (const auto& id : removed) unlink(id);
        for (const auto& id : next->changes.direct) {
            auto previous = base->entities.find(id);
            if (previous != base->entities.end() && previous->second->dependencies == next->entities.at(id)->dependencies) continue;
            unlink(id);
            for (const auto& dependency : next->entities.at(id)->dependencies) {
                if (dependency.empty() || !next->entities.count(dependency))
                    throw std::invalid_argument("Missing dependency for " + id);
                next->edgeCount += consumersFor(dependency).insert(id).second;
            }
        }
        for (const auto& [id, consumers] : changedConsumers) {
            if (consumers.empty()) next->consumers.erase(id);
            else next->consumers.set(id, consumers);
        }
        for (const auto& id : removed)
            if (next->consumers.count(id)) throw std::invalid_argument("Removed resource still referenced");
        if (next->edgeCount > limits_.edges) throw std::length_error("Dependency budget exceeded");
        // Reverse traversal is linear in affected edges; cycles terminate via visited set.
        next->changes.affected = next->changes.direct;
        std::deque<std::string> pending(next->changes.direct.begin(), next->changes.direct.end());
        while (!pending.empty()) {
            auto id = std::move(pending.front()); pending.pop_front();
            auto found = next->consumers.find(id);
            if (found == next->consumers.end()) continue;
            for (const auto& consumer : found->second)
                if (next->changes.affected.insert(consumer).second) pending.push_back(consumer);
        }
        for (const auto& id : next->changes.affected) {
            if (changed.count(id)) continue;
            auto entity = std::make_shared<Entity>(*next->entities.at(id));
            entity->revision = next->revision;
            next->entities.set(id, entity); // Reuse ALL unedited resource buffers.
        }
        // Check raw/pre-existing prepared footprint before invoking the backend.
        size_t bytes = base->residentBytes;
        auto subtractOld = [&](const std::string& id) {
            auto found = base->entities.find(id);
            if (found == base->entities.end()) return;
            for (const auto& pair : found->second->buffers) {
                bytes -= pair.second->source.size();
                bytes -= pair.second->prepared.size();
            }
        };
        for (const auto& id : removed) subtractOld(id);
        for (const auto& id : next->changes.direct) subtractOld(id);
        for (const auto& id : next->changes.direct)
            for (const auto& pair : next->entities.at(id)->buffers) {
                addBudget(bytes, pair.second->source.size(), limits_.bytes);
                addBudget(bytes, pair.second->prepared.size(), limits_.bytes);
            }
        for (const auto& [id, fields] : dirty) {
            if (identity) {
                next->changes.preparedBuffers += fields.size();
                continue;
            }
            auto& entity = changed.at(id);
            for (auto field : fields) {
                const auto& source = entity->buffers.at(field)->source;
                Bytes prepared = encode(entity->kind, field, source);
                addBudget(bytes, prepared.size(), limits_.bytes);
                next->changes.preparedBytes += prepared.size();
                ++next->changes.preparedBuffers;
                entity->buffers[field] = std::make_shared<const Buffer>(Buffer{next->revision, source, std::move(prepared)});
            }
        }
        next->residentBytes = bytes;
        return Candidate(owner_, base, std::move(next));
    }
    bool commit(const Candidate& candidate) {
        checkThread();
        if (candidate.owner != owner_ || candidate.base != active_ || !candidate.next) return false;
        active_ = candidate.next;
        return true;
    }
private:
    static void addBudget(size_t& total, size_t amount, size_t limit) {
        if (total > limit || amount > limit - total) throw std::length_error("Scene resource budget exceeded");
        total += amount;
    }
    void checkThread() const {
        if (std::this_thread::get_id() != coordinator_) throw std::logic_error("Foreign scene coordinator");
    }
    const std::thread::id coordinator_ = std::this_thread::get_id();
    const std::shared_ptr<const int> owner_ = std::make_shared<const int>(0);
    Limits limits_;
    View active_;
};
} // namespace xpu2::indexed
