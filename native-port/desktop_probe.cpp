#include <moonray/common/mcrt_util/Wait.h>
#include <moonray/application/ChangeWatcher.h>
#include <scene_rdl2/common/grid_util/NumaUtil.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <vector>

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
template<class T> void checkWait() {
    std::atomic<T> signal{0};
    std::atomic<int> ready{0}, done{0};
    std::vector<std::thread> workers;
    for (int i = 0; i != 3; ++i) workers.emplace_back([&] {
        ++ready;
        wait(signal, T(0), std::memory_order_acquire);
        if (signal.load() == T(1)) ++done;
    });
    while (ready.load() != 3) std::this_thread::yield();
    std::this_thread::sleep_for(std::chrono::milliseconds(30));
    require(done.load() == 0, "wait returned before value changed");
    signal.store(T(1), std::memory_order_release);
    notify_all(signal);
    for (auto& worker : workers) worker.join();
    require(done.load() == 3, "notify_all missed a waiter");
    wait(signal, T(0)); // An already changed value must return immediately.
    signal.store(T(0));
    std::thread one([&] { wait(signal, T(0)); });
    signal.store(T(1));
    notify_one(signal);
    one.join();
}
int main() try {
    uintptr_t bytes = 65536, before = 0, after = 0;
    asm volatile("movq %%rsp, %1\n\tcall __chkstk\n\tmovq %%rsp, %2"
                 : "+a"(bytes), "=&r"(before), "=&r"(after) : : "memory", "cc");
    require(bytes == 65536 && before == after, "ISPC stack probe changed its ABI registers");
    checkWait<uint8_t>(); checkWait<uint16_t>(); checkWait<uint32_t>(); checkWait<uint64_t>();
    scene_rdl2::grid_util::NumaUtil topology;
    require(topology.getTotalNumaNode() > 0, "missing NUMA topology");
    const auto* node = topology.getNumaNode(0);
    require(node && !node->getCpuIdList().empty(), "missing CPU topology");
    void* pages = node->alloc(8192);
    std::memset(pages, 42, 8192);
    require(node->alignmentSizeCheck(64), "cache alignment unavailable");
    require(reinterpret_cast<uintptr_t>(pages) % 64 == 0, "unaligned pages");
    require(node->isBelongMem(pages, 8192), "pages on unexpected NUMA node");
    node->free(pages, 8192);
    const auto filename = std::filesystem::temp_directory_path() /
        ("MoonRay watch test " + std::to_string(GetCurrentProcessId()) + ".txt");
    std::unique_ptr<moonray::ChangeWatcher> watcher(moonray::ChangeWatcher::CreateChangeWatcher());
    watcher->watchFile(filename.u8string());
    require(!watcher->hasChanged(), "unmodified watch reported change");
    { std::ofstream out(filename); out << "created"; }
    watcher->waitForChange();
    std::set<std::string> changed;
    require(watcher->hasChanged(&changed) && changed.count(filename.u8string()), "creation was lost");
    require(!watcher->hasChanged(), "change delivered twice");
    { std::ofstream out(filename, std::ios::app); out << " modified"; }
    require(watcher->hasChanged(), "modification was missed");
    std::filesystem::remove(filename);
    require(watcher->hasChanged(), "deletion was missed");
    std::cout << "Windows stack probing, wait/notify, NUMA allocation and file changes passed\n";
    return 0;
} catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
