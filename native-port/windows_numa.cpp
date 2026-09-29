// Native Windows topology and page allocation for the desktop renderer.
#include <scene_rdl2/common/grid_util/NumaUtil.h>
#include <scene_rdl2/common/grid_util/CpuSocketUtil.h>
#include <windows.h>
#include <psapi.h>
#include <algorithm>
#include <sstream>
#include <stdexcept>

namespace scene_rdl2 { namespace grid_util {
namespace {
size_t pageSize() { SYSTEM_INFO info{}; GetSystemInfo(&info); return info.dwPageSize; }
unsigned memoryNode(void* address) {
    PSAPI_WORKING_SET_EX_INFORMATION info{};
    info.VirtualAddress = address;
    if (!QueryWorkingSetEx(GetCurrentProcess(), &info, sizeof(info)) || !info.VirtualAttributes.Valid)
        throw std::runtime_error("Cannot query NUMA node for a nonresident memory page");
    return info.VirtualAttributes.Node;
}
}
NumaNode::NumaNode(unsigned node, unsigned total, size_t memory,
                   const std::vector<unsigned>& cpus, const std::vector<int>& distances)
    : mNodeId(node), mTotalNode(total), mMemSize(memory), mPageSize(pageSize()),
      mCpuIdList(cpus), mNodeDistance(distances) {}
void* NumaNode::alloc(size_t bytes) const {
    if (!bytes) return nullptr;
    void* result = VirtualAllocExNuma(GetCurrentProcess(), nullptr, bytes,
        MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE, mNodeId);
    if (!result) throw std::bad_alloc();
    return result;
}
void NumaNode::free(void* memory, size_t) const {
    if (memory && !VirtualFree(memory, 0, MEM_RELEASE))
        throw std::runtime_error("VirtualFree failed");
}
bool NumaNode::isBelongMem(void* memory, size_t bytes) const {
    if (!bytes) return true;
    const auto begin = reinterpret_cast<uintptr_t>(memory);
    const auto first = begin - begin % mPageSize;
    for (auto p = first; p < begin + bytes; p += mPageSize)
        if (memoryNode(reinterpret_cast<void*>(p)) != mNodeId) return false;
    return true;
}
bool NumaNode::isBelongCpu(unsigned cpu) const {
    return std::find(mCpuIdList.begin(), mCpuIdList.end(), cpu) != mCpuIdList.end();
}
bool NumaNode::alignmentSizeCheck(size_t alignment) const {
    return alignment && !(alignment & (alignment - 1)) && mPageSize % alignment == 0;
}
std::string NumaNode::show() const {
    std::ostringstream out;
    out << "Windows NUMA node " << mNodeId << " available bytes:" << mMemSize << " CPUs:";
    for (auto cpu : mCpuIdList) out << ' ' << cpu;
    return out.str();
}
NumaUtil::NumaUtil() { reset("localhost"); parserConfigure(); }
void NumaUtil::reset(const std::string& mode) {
    if (mode != "localhost") throw std::runtime_error("Windows NUMA supports localhost topology only");
    if (GetActiveProcessorGroupCount() != 1)
        throw std::runtime_error("This Windows renderer currently supports one processor group (up to 64 CPUs)");
    ULONG highest = 0;
    if (!GetNumaHighestNodeNumber(&highest)) throw std::runtime_error("Cannot query Windows NUMA topology");
    mNumaNodeTbl.clear();
    for (ULONG node = 0; node <= highest; ++node) {
        GROUP_AFFINITY mask{};
        ULONGLONG available = 0;
        if (!GetNumaNodeProcessorMaskEx(static_cast<USHORT>(node), &mask) ||
            !GetNumaAvailableMemoryNodeEx(static_cast<USHORT>(node), &available))
            throw std::runtime_error("Cannot query Windows NUMA node");
        std::vector<unsigned> cpus;
        for (unsigned i = 0; i < 64; ++i) if (mask.Mask & (KAFFINITY(1) << i)) cpus.push_back(i);
        // Windows does not expose Linux's distance table. Keep a neutral relative-cost hint.
        std::vector<int> distance(highest + 1, 20);
        distance[node] = 10;
        mNumaNodeTbl.emplace_back(node, highest + 1, available, cpus, distance);
    }
}
const NumaNode* NumaUtil::getNumaNode(unsigned node) const {
    return node < mNumaNodeTbl.size() ? &mNumaNodeTbl[node] : nullptr;
}
const NumaNode* NumaUtil::findNumaNodeByCpuId(unsigned cpu) const {
    for (const auto& node : mNumaNodeTbl) if (node.isBelongCpu(cpu)) return &node;
    return nullptr;
}
int NumaUtil::cpuIdToNodeId(unsigned cpu) const {
    const auto* node = findNumaNodeByCpuId(cpu);
    return node ? static_cast<int>(node->getNodeId()) : -1;
}
std::vector<unsigned> NumaUtil::genActiveNumaNodeIdTblByCpuIdTbl(const std::vector<unsigned>& cpus) const {
    std::vector<unsigned> result;
    for (auto cpu : cpus) {
        const auto* node = findNumaNodeByCpuId(cpu);
        if (!node) throw std::runtime_error("CPU not present in Windows NUMA topology");
        if (std::find(result.begin(), result.end(), node->getNodeId()) == result.end()) result.push_back(node->getNodeId());
    }
    std::sort(result.begin(), result.end());
    return result;
}
unsigned NumaUtil::findNumaNodeByMemAddr(void* address) { return memoryNode(address); }
std::string NumaUtil::show() const {
    std::string result;
    for (const auto& node : mNumaNodeTbl) result += node.show() + '\n';
    return result;
}
void NumaUtil::parserConfigure() {
    mParser.description("Windows NUMA topology");
    mParser.opt("show", "", "Show NUMA topology", [&](Arg& arg) { return arg.msg(show()); });
}
bool NumaUtil::resetCmd(const std::string& mode, const MsgFunc& output) {
    try { reset(mode); return output(show()); }
    catch (const std::exception& e) { output(e.what()); return false; }
}
}}
