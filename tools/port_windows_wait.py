from pathlib import Path
root = Path(__file__).resolve().parents[1]
path = root / 'upstream/openmoonray/moonray/moonray/lib/common/mcrt_util/Wait.h'
text = path.read_text(encoding='utf-8')
if 'WaitOnAddress' not in text:
    text = text.replace('#if defined(_MSC_FULL_VER)', '#if defined(_WIN32)')
    text = text.replace('defined(__GNUC__) && !defined(__clang__)', 'defined(__GNUC__) && !defined(__clang__) && !defined(_WIN32)')
    text = text.replace('#if defined(__clang__)\n#include <climits>', '#if defined(__clang__) && !defined(_WIN32)\n#include <climits>')
    text = text.replace('    a.wait(old, order);', '    a.wait(old, order);')
    marker = '#if defined(__cpp_lib_atomic_wait)\n    a.wait(old, order);'
    text = text.replace(marker, '''#if defined(_WIN32)
    static_assert(sizeof(T) == 1 || sizeof(T) == 2 || sizeof(T) == 4 || sizeof(T) == 8,
                  "Windows address wait requires a 1, 2, 4 or 8 byte atomic");
    static_assert(sizeof(a) == sizeof(T), "Atomic storage must match Windows wait size");
    while (wait_impl::atomic_compare(a.load(order), old))
        WaitOnAddress(const_cast<std::atomic<T>*>(std::addressof(a)), &old, sizeof(T), INFINITE);
#elif defined(__cpp_lib_atomic_wait)
    a.wait(old, order);''')
    text = text.replace('#if defined(__cpp_lib_atomic_wait)\n    a.notify_one();',
                        '#if defined(_WIN32)\n    WakeByAddressSingle(std::addressof(a));\n#elif defined(__cpp_lib_atomic_wait)\n    a.notify_one();')
    text = text.replace('#if defined(__cpp_lib_atomic_wait)\n    a.notify_all();',
                        '#if defined(_WIN32)\n    WakeByAddressAll(std::addressof(a));\n#elif defined(__cpp_lib_atomic_wait)\n    a.notify_all();')
    path.write_text(text, encoding='utf-8')
