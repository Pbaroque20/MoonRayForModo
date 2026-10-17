// Shared across diagnostic translation units; separate from renderer progress.
#pragma once
#include <cstdio>
#include <cstdlib>
inline FILE* xpu2TraceOutput()
{
    static FILE* stream=[]() {
        const char* path=std::getenv("XPU2_TRACE_FILE");
        if (!path || !*path) return stderr;
        FILE* file=std::fopen(path,"w");
        if (!file) std::fprintf(stderr,"XPU2: cannot open diagnostic trace file\n");
        return file ? file : stderr;
    }();
    return stream;
}
