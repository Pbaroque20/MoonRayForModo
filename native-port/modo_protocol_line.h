#pragma once
#include <cstdio>
#include <mutex>
#include <string>
// One line of the protocol the host reads from standard output, written whole. Lines are written by more than one
// thread (the session's own, and the one that tells of the workers' tiles), and a line broken into by another would
// be lost on the host: so each goes out in a single write, one at a time. It begins on a line of its own whatever
// the renderer was in the middle of printing.
inline void modoProtocolLine(const std::string& text) {
    static std::mutex mutex;
    const std::string whole = "\n" + text + "\n";
    std::lock_guard<std::mutex> lock(mutex);
    std::fwrite(whole.data(), 1, whole.size(), stdout);
    std::fflush(stdout);
}
