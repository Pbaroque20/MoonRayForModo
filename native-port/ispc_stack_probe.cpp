// ISPC's Windows target uses Microsoft's name for the x64 stack-probe helper.
// GNU's equivalent probes every guard page and preserves the same registers.
// A tail jump is essential: a C++ wrapper would change the stack being probed.
#if !defined(_WIN64) || !defined(__GNUC__)
#error This adapter requires the native x64 GNU Windows toolchain
#endif
asm(".text\n"
    ".globl __chkstk\n"
    ".def __chkstk; .scl 2; .type 32; .endef\n"
    "__chkstk:\n"
    "jmp ___chkstk_ms\n");
