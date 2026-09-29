#include <moonray/application/ChangeWatcher.h>
#include <filesystem>
#include <chrono>
#include <thread>
#include <mutex>

namespace moonray {
class WindowsChangeWatcher final : public ChangeWatcher {
    struct Stamp {
        bool exists;
        std::filesystem::file_time_type modified;
        uintmax_t size;
        bool operator!=(const Stamp& other) const {
            return exists != other.exists || modified != other.modified || size != other.size;
        }
    };
    static Stamp stamp(const std::string& filename) {
        auto path = std::filesystem::u8path(filename);
        std::error_code error;
        Stamp value{};
        value.exists = std::filesystem::exists(path, error);
        if (value.exists) {
            value.modified = std::filesystem::last_write_time(path, error);
            value.size = std::filesystem::file_size(path, error);
        }
        return value;
    }
    std::map<std::string, Stamp> files;
    std::set<std::string> pending;
    std::mutex mutex;
    void scan() {
        for (auto& entry : files) {
            const auto current = stamp(entry.first);
            if (current != entry.second) { pending.insert(entry.first); entry.second = current; }
        }
    }
public:
    void watchFile(const std::string& filename) override {
        std::lock_guard<std::mutex> lock(mutex);
        files.emplace(filename, stamp(filename));
    }
    bool hasChanged(std::set<std::string>* changed) override {
        std::lock_guard<std::mutex> lock(mutex);
        scan();
        if (pending.empty()) return false;
        if (changed) changed->insert(pending.begin(), pending.end());
        pending.clear();
        return true;
    }
    void waitForChange() override {
        for (;;) {
            { std::lock_guard<std::mutex> lock(mutex); scan(); if (!pending.empty()) return; }
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
    }
};
ChangeWatcher* ChangeWatcher::CreateChangeWatcher() { return new WindowsChangeWatcher; }
}
