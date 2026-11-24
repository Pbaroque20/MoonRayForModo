// Rhea's radiance cache (the user, 2026-11-24): what XPU2 RT (Rhea) has learned of a scene (its ObjectStore, the light on
// the surfaces) kept for the next time realtime is turned on for the same scene, in memory, or on disk as a file a scene
// in the kit's Cache folder (Preview Preferences: Rhea radiance cache, In memory / On disk).
//
// - The scene's key (SceneKey): every object of the scene as XPU2's canonical index holds it (objects the fast paths
//   edited since it was published read from the session's scene), its attributes' bytes hashed, but for what does not
//   change the light on the surfaces: the cameras, XPU2's own settings (/modo/xpu2/..., which say whether realtime is
//   on), the outputs (named anew at each command) and the scene variables' picture size, samples and files. An edit that
//   changes anything else (a light, a material, a mesh, a move) is another key, as Rhea forgets its store on any edit but
//   the camera's. Buffers the index keeps across edits are hashed once (memo).
// - Kept (StoreCache::park): the store Rhea forgets at an edit or a new scene, with its key; taken back
//   (StoreCache::restore) when a realtime scene of that key comes (realtime turned on again, an edit undone). Up to four
//   kept in memory besides the live one (1 GB); on disk, a file a key (<folder>/<key>.rhea), written when one is set aside, when a
//   realtime frame ends at most every 30 s while it has learned more, and when the session quits; read when realtime
//   starts on a scene of that key with nothing in memory (also after Modo is restarted).
// - Flushed: the kit writes <folder>/flush.stamp (cache_folder.rhea_flush): "<count> memory" drops what the session holds
//   (on disk the live store written first), "<count> clear" drops it without writing (Clear Radiance Cache, which
//   removes the files). A session quits with the scene (Panel._scene_closed): what it held in memory goes with it.
//
// XPU2_SESSION_RHEA_CACHE: memory (the default), disk or off; XPU2_SESSION_RHEA_CACHE_FOLDER: the folder (else
// MOONRAY_MODO_CACHE/Rhea).
#pragma once
#include "object_warp.h"
#include "../xpu2/rdl_scene_index.h"
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <map>
#include <memory>
#include <string>
#include <system_error>
#include <unordered_map>

namespace rhea {
namespace cachefs = std::filesystem;

// A 128-bit hash of a scene's light-shaping content (the file comment's SceneKey), as 32 hexadecimal digits.
class SceneKey {
public:
    // scene: the canonical index as last published; source: the session's scene, whose objects still dirty (edited by
    // the camera's or the placements' and lights' fast paths, which do not publish the canonical copy) are read from it
    // instead, encoded as the canonical capture encodes them (so that the same values give the same key either way).
    std::string of(const xpu2::indexed::View& scene, const scene_rdl2::rdl2::SceneContext* source = nullptr) {
        namespace ix = xpu2::indexed;
        namespace ri = xpu2::rdlindex;
        if (!scene) return std::string();
        std::uint64_t h[2] = {0x6A09E667F3BCC908ull, 0xBB67AE8584CAA73Bull};
        size_t objects = 0;
        std::map<std::string, const scene_rdl2::rdl2::SceneObject*> dirty;
        if (source)
            for (auto it = source->beginSceneObject(); it != source->endSceneObject(); ++it)
                if (it->second->isDirty()) dirty[ri::objectId(it->second->getName())] = it->second;
        auto add = [&](const std::uint64_t e[2]) {
            h[0] += mix(e[0] ^ e[1]), h[1] += mix(e[1] + 0x632BE59BD9B4E019ull * e[0]);
            ++objects;
        };
        auto attribute = [&](std::uint64_t e[2], const std::string& aid, ix::Field field, const std::uint64_t b[2]) {
            std::uint64_t a[2] = {mixString(aid, 3), 0};
            a[0] = mix(a[0] ^ b[0] ^ std::uint64_t(field)), a[1] = mix(a[1] + b[1] + std::uint64_t(field));
            // The attributes in any order: summed.
            e[0] += mix(a[0]), e[1] += mix(a[1] ^ 0x9E3779B97F4A7C15ull);
        };
        for (const auto& [id, entity] : scene->entities) {
            if (!entity || entity->kind == ix::Kind::Attribute || entity->kind == ix::Kind::Camera || dirty.count(id)) continue;
            // The object's name and class (its metadata), then each of its attributes' bytes.
            std::string name, cls;
            const auto meta = entity->buffers.find(ix::Field::Parameters);
            if (meta != entity->buffers.end() && meta->second) {
                try {
                    ri::Reader r{meta->second->source};
                    name = ri::Codec<std::string>::get(r);
                    cls = ri::Codec<std::string>::get(r);
                } catch (...) {
                }
            }
            if (lightless(name, cls)) continue;
            std::uint64_t e[2] = {mixString(id, 1), mixString(cls, 2)};
            const std::string prefix = "a:" + std::to_string(name.size()) + ":" + name;
            for (const std::string& aid : entity->dependencies) {
                // Its name: past the object's, its length and a colon.
                std::string attr;
                if (aid.compare(0, prefix.size(), prefix) == 0) {
                    const size_t colon = aid.find(':', prefix.size());
                    if (colon != std::string::npos) attr = aid.substr(colon + 1);
                }
                if (pictureOnly(cls, attr)) continue;
                const auto found = scene->entities.find(aid);
                if (found == scene->entities.end() || !found->second) continue;
                for (const auto& [field, buffer] : found->second->buffers) {
                    if (!buffer) continue;
                    std::uint64_t b[2];
                    bufferHash(buffer, b);
                    attribute(e, aid, field, b);
                }
            }
            add(e);
        }
        for (const auto& [id, object] : dirty) {
            const std::string& name = object->getName();
            const std::string cls = object->getSceneClass().getName();
            if (ri::kind(*object) == ix::Kind::Camera || lightless(name, cls)) continue;
            std::uint64_t e[2] = {mixString(id, 1), mixString(cls, 2)};
            const auto& sc = object->getSceneClass();
            for (auto a = sc.beginAttributes(); a != sc.endAttributes(); ++a) {
                if (pictureOnly(cls, (*a)->getName())) continue;
                const ri::Writer w = ri::encodeAttribute(*object, **a);
                std::uint64_t b[2];
                bytesHash(w.bytes, b);
                hashedBytes += double(w.bytes.size());
                attribute(e, ri::attributeId(name, (*a)->getName()), ri::field(**a), b);
            }
            add(e);
        }
        if (!objects) return std::string();
        // Buffers no longer held, let go now and then.
        if (memo.size() > 2 * kept + 4096) {
            for (auto it = memo.begin(); it != memo.end();) it = it->second.held.expired() ? memo.erase(it) : std::next(it);
            kept = memo.size();
        }
        char text[40];
        std::snprintf(text, sizeof text, "%016llx%016llx", (unsigned long long)mix(h[0]), (unsigned long long)mix(h[1] ^ objects));
        return text;
    }
    double hashedBytes = 0;  // bytes hashed since the session began (the memo's misses)

private:
    struct Held {
        std::weak_ptr<const xpu2::indexed::Buffer> held;
        std::uint64_t h[2];
    };
    std::unordered_map<const void*, Held> memo;
    size_t kept = 0;
    // What changes no light on the surfaces: XPU2's own settings (/modo/xpu2/..., whether realtime is on and its
    // sampling), the outputs (their files are named anew at each command), and the cameras (left out by kind).
    static bool lightless(const std::string& name, const std::string& cls) {
        return name.compare(0, 11, "/modo/xpu2/") == 0 || cls == "RenderOutput";
    }
    // The scene variables' picture, samples and files.
    static bool pictureOnly(const std::string& cls, const std::string& attr) {
        if (cls != "SceneVariables" || attr.empty()) return false;
        static const char* const names[] = {"image_width", "image_height", "res", "pixel_samples", "sampling_mode", "min_adaptive_samples",
                                            "max_adaptive_samples", "target_adaptive_error", "aperture_window", "region_window", "sub_viewport",
                                            "camera", "dicing_camera", "frame", "fps", "threads", "machine_id", "num_machines", "task_distribution_type",
                                            "progressive", "progress_mode", "two_stage_output", "debug", "info", "fatal_color", "stats_file"};
        for (const char* n : names)
            if (attr == n) return true;
        return attr.find("file") != std::string::npos || attr.find("checkpoint") != std::string::npos ||
               attr.find("resume") != std::string::npos || attr.find("debug") != std::string::npos || attr.find("output") != std::string::npos;
    }
    static std::uint64_t mix(std::uint64_t x) {
        x ^= x >> 30, x *= 0xBF58476D1CE4E5B9ull;
        x ^= x >> 27, x *= 0x94D049BB133111EBull;
        return x ^ (x >> 31);
    }
    static std::uint64_t mixString(const std::string& s, std::uint64_t seed) {
        std::uint64_t h = 0xCBF29CE484222325ull ^ seed;
        for (unsigned char c : s) h = (h ^ c) * 0x100000001B3ull;
        return mix(h);
    }
    static void bytesHash(const std::vector<std::uint8_t>& v, std::uint64_t out[2]) {
        std::uint64_t a = 0x9E3779B97F4A7C15ull ^ v.size(), b = 0xC2B2AE3D27D4EB4Full + v.size();
        const size_t n = v.size() / 8;
        const std::uint8_t* p = v.data();
        for (size_t i = 0; i < n; ++i) {
            std::uint64_t w;
            std::memcpy(&w, p + i * 8, 8);
            a = (a ^ w) * 0x100000001B3ull, a = (a << 29) | (a >> 35);
            b = (b + w) * 0xFF51AFD7ED558CCDull, b ^= b >> 33;
        }
        for (size_t i = n * 8; i < v.size(); ++i) a = (a ^ p[i]) * 0x100000001B3ull, b = (b + p[i]) * 0xC4CEB9FE1A85EC53ull;
        out[0] = mix(a), out[1] = mix(b ^ a);
    }
    void bufferHash(const std::shared_ptr<const xpu2::indexed::Buffer>& buffer, std::uint64_t out[2]) {
        const auto found = memo.find(buffer.get());
        if (found != memo.end() && !found->second.held.expired() && found->second.held.lock() == buffer) {
            out[0] = found->second.h[0], out[1] = found->second.h[1];
            return;
        }
        bytesHash(buffer->source, out);
        hashedBytes += double(buffer->source.size());
        Held& m = memo[buffer.get()];
        m.held = buffer, m.h[0] = out[0], m.h[1] = out[1];
    }
};

// The radiance cache itself (the file comment).
class StoreCache {
public:
    enum Mode { Off, Memory, Disk };
    Mode mode = Memory;
    cachefs::path folder;
    std::string liveKey;  // the scene the live store is of ("": not known)
    SceneKey keys;

    StoreCache() {
        const char* m = std::getenv("XPU2_SESSION_RHEA_CACHE");
        const std::string v = m ? m : "memory";
        mode = v == "disk" ? Disk : v == "off" || v == "0" ? Off : Memory;
        if (const char* f = std::getenv("XPU2_SESSION_RHEA_CACHE_FOLDER")) folder = cachefs::u8path(f);
        else if (const char* c = std::getenv("MOONRAY_MODO_CACHE")) folder = cachefs::u8path(c) / "Rhea";
        flushSeen = readStamp();
    }
    bool on() const { return mode != Off; }
    const char* modeName() const { return mode == Disk ? "on disk" : mode == Memory ? "in memory" : "off"; }

    // The live store set aside with its key (an edit, a new scene), the newest of those kept in memory (at most
    // KeptStores, KeptBytes between them: the oldest let go). On disk it is written at once only where none was written
    // for 10 s (an item dragged in realtime sets a store aside at every step); else when the session quits (saveAll).
    static constexpr size_t KeptStores = 4, KeptBytes = size_t(1) << 30;
    void park(ObjectStore& live) {
        if (!on() || live.empty() || liveKey.empty()) return;
        Kept k;
        k.key = liveKey;
        k.saved = live.cells() == savedCells;
        if (mode == Disk && !k.saved && sinceSave() >= 10.0) k.saved = save(live, liveKey);
        k.store = std::make_unique<ObjectStore>(std::move(live));
        live = ObjectStore{};
        live.clear();
        savedCells = 0;
        for (auto it = kept.begin(); it != kept.end(); ++it)
            if (it->key == k.key) {
                kept.erase(it);
                break;
            }
        kept.insert(kept.begin(), std::move(k));
        size_t bytes = 0, count = 0;
        for (auto it = kept.begin(); it != kept.end();) {
            bytes += it->store->bytes(), ++count;
            if (count > 1 && (count > KeptStores || bytes > KeptBytes)) {
                // Let go: on disk, written first where it was not.
                if (mode == Disk && !it->saved) save(*it->store, it->key);
                it = kept.erase(it);
            } else
                ++it;
        }
    }
    // The session quitting: on disk, the live store and those set aside written where they have not been.
    void saveAll(const ObjectStore& live) {
        if (mode != Disk || readStamp() != flushSeen) return;  // a flush asked and not taken yet: nothing written
        saveLive(live, 0);
        for (Kept& k : kept)
            if (!k.saved && k.key != liveKey) k.saved = save(*k.store, k.key);
    }
    // The store of this key taken back into the live one, which is empty: one kept in memory, or its file. Where it
    // came from ("" none).
    std::string restore(const std::string& key, ObjectStore& live) {
        if (!on() || key.empty() || !live.empty()) return std::string();
        for (auto it = kept.begin(); it != kept.end(); ++it) {
            if (it->key != key) continue;
            const ObjectStore::Options op = live.op;
            live = std::move(*it->store);
            const bool saved = it->saved;
            kept.erase(it);
            live.op.threads = op.threads;
            live.renewed();
            savedCells = saved ? live.cells() : 0;
            return "memory";
        }
        if (mode == Disk && load(key, live)) {
            savedCells = live.cells();
            return "disk";
        }
        return std::string();
    }
    // The live store written to its file where it has learned more since last written (at most every `every` seconds).
    void saveLive(const ObjectStore& live, double every) {
        if (mode != Disk || liveKey.empty() || live.empty() || live.cells() == savedCells) return;
        if (every > 0 && sinceSave() < every) return;
        if (readStamp() != flushSeen) return;  // a flush asked and not taken yet (Clear Radiance Cache): nothing written
        if (save(live, liveKey)) savedCells = live.cells();
    }
    // The kit's flush (flush.stamp changed since it was last seen): true where it asked, the live store and the one kept
    // dropped (on disk, the live one written first unless the kit cleared the files).
    bool flushAsked(ObjectStore& live) {
        const std::string stamp = readStamp();
        if (stamp == flushSeen) return false;
        flushSeen = stamp;
        const bool clearing = stamp.find("clear") != std::string::npos;
        if (mode == Disk && !clearing) saveAll(live);
        live.clear();
        kept.clear();
        savedCells = 0;
        return true;
    }
    size_t keptStores() const { return kept.size(); }
    double lastSeconds = 0;  // the last file's write or read
    std::string lastError;

private:
    struct Kept {
        std::string key;
        std::unique_ptr<ObjectStore> store;
        bool saved = false;  // written to its file as it is
    };
    std::vector<Kept> kept;  // set aside, the newest first
    std::string flushSeen;
    size_t savedCells = 0;  // the live store's cells when last written (0: not written)
    std::chrono::steady_clock::time_point lastSave{};
    double sinceSave() const {
        return lastSave.time_since_epoch().count() ? std::chrono::duration<double>(std::chrono::steady_clock::now() - lastSave).count() : 1e9;
    }

    cachefs::path fileOf(const std::string& key) const { return folder / (key + ".rhea"); }
    std::string readStamp() const {
        if (folder.empty()) return std::string();
        std::FILE* f = _wfopen((folder / "flush.stamp").wstring().c_str(), L"rb");
        if (!f) return std::string();
        char text[128] = {};
        const size_t n = std::fread(text, 1, sizeof text - 1, f);
        std::fclose(f);
        return std::string(text, n);
    }
    bool save(const ObjectStore& store, const std::string& key) {
        if (folder.empty() || key.empty() || store.empty()) return false;
        const auto began = std::chrono::steady_clock::now();
        std::error_code ignored;
        cachefs::create_directories(folder, ignored);
        const cachefs::path target = fileOf(key), staged = folder / (key + ".rhea.tmp");
        std::FILE* f = _wfopen(staged.wstring().c_str(), L"wb");
        if (!f) return lastError = "cannot write " + staged.u8string(), false;
        const bool ok = std::fwrite(key.data(), 1, key.size(), f) == key.size() && store.save(f);
        const bool closed = std::fclose(f) == 0;
        if (!ok || !closed) {
            cachefs::remove(staged, ignored);
            return lastError = "cannot write " + staged.u8string(), false;
        }
        cachefs::rename(staged, target, ignored);
        if (ignored) {
            cachefs::remove(staged, ignored);
            return lastError = "cannot replace " + target.u8string(), false;
        }
        lastSave = std::chrono::steady_clock::now();
        lastSeconds = std::chrono::duration<double>(lastSave - began).count();
        std::printf("MoonRay XPU2: Rhea: radiance cache written to %s (%zu cells) in %.3f s\n", target.u8string().c_str(), store.cells(), lastSeconds);
        std::fflush(stdout);
        return true;
    }
    bool load(const std::string& key, ObjectStore& live) {
        if (folder.empty()) return false;
        const auto began = std::chrono::steady_clock::now();
        std::FILE* f = _wfopen(fileOf(key).wstring().c_str(), L"rb");
        if (!f) return false;
        std::string held(key.size(), '\0');
        ObjectStore read;
        read.op = live.op;
        const bool ok = std::fread(held.data(), 1, held.size(), f) == held.size() && held == key && read.load(f);
        std::fclose(f);
        if (!ok) return false;
        live = std::move(read);
        live.renewed();
        lastSeconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - began).count();
        // Touched: the newest used is the last a trim lets go.
        std::error_code ignored;
        cachefs::last_write_time(fileOf(key), cachefs::file_time_type::clock::now(), ignored);
        return true;
    }
};
}  // namespace rhea
