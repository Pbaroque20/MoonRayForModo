// Shared host/CUDA wire constants. Keep this header free of host-only dependencies.
#pragma once
namespace xpu2 { namespace resident { namespace wire {
constexpr unsigned magic=0x32525358u, updateBit=0x80000000u, inactive=0xffffffffu;
constexpr unsigned slots=128, lanes=8, sampleWords=24, resultWords=9;
constexpr unsigned headerWords=5, descriptorWords=5, tagWords=5;
constexpr unsigned commonWords=lanes*sampleWords;
constexpr unsigned entryWords=tagWords+commonWords, updateWords=1+entryWords;
constexpr unsigned maxPackets=64, maxSamples=maxPackets*lanes;
constexpr unsigned maxWords=headerWords+maxSamples*descriptorWords+maxPackets*updateWords;
constexpr unsigned rejected=3, invalid=2, success=0;
static_assert(sizeof(unsigned)==4, "Resident wire requires 32-bit words");
}}}
