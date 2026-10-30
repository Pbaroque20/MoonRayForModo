// Test DLL: execute the exact queue stress code behind a C ABI boundary.
#define main xpu2QueueStressMain
#include "native_queue_stress.cc"
#undef main
extern "C" __declspec(dllexport) int xpu2QueueRun(const char* scenario,const char* capture) {
    char name[]="queue-dll-probe";
    char* argv[]={name,const_cast<char*>(scenario),const_cast<char*>(capture)};
    return xpu2QueueStressMain(3,argv);
}
