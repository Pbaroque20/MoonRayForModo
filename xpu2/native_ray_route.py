"""Opt-in small-batch GPU routing for isolated native scheduling diagnostics."""
from .native_gpu_paths import once

def header(text):
    text=once(text,'#pragma once','#pragma once\n#include <cstdlib>\n#include <cstring>')
    return once(text,'if ((mNumThreadsUsingGPU.load() < maxThreads) && numRays > 1024) {',
        """// Preserve the native busy-device admission guard. The opt-in changes
        // only the small-batch threshold, never GPU availability or support.
        const char* route=std::getenv("XPU2_SMALL_BATCH_GPU");
        const bool smallBatchGpu=route && !std::strcmp(route,"1");
        if ((mNumThreadsUsingGPU.load() < maxThreads) && (numRays > 1024 || smallBatchGpu)) {""")
