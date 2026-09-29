"""Keep the two upstream wire codecs 64-bit on Windows' LLP64 data model."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1] / 'upstream/openmoonray/moonray/scene_rdl2/lib'
files = ['render/cache/ValueContainerUtils.h', 'render/cache/ValueContainerEnqueue.h',
         'render/cache/ValueContainerDequeue.h', 'scene/rdl2/ValueContainerUtil.h',
         'scene/rdl2/ValueContainerEnq.h', 'scene/rdl2/ValueContainerDeq.h',
         'scene/rdl2/ValueContainerEnq.cc']
for name in files:
    path = root / name
    before = path.read_text(encoding='utf-8')
    lines = []
    for line in before.splitlines(keepends=True):
        code, delimiter, comment = line.partition('//')
        code = re.sub(r'\bunsigned long\b', 'uint64_t', code)
        code = re.sub(r'\blong\b', 'int64_t', code)
        lines.append(code + delimiter + comment)
    after = ''.join(lines)
    if '#include <cstdint>' not in after:
        after = after.replace('#pragma once', '#pragma once\n#include <cstdint>')
    after = after.replace('(l >> 63) ^ (l << 1)',
                          '(static_cast<uint64_t>(l) << 1) ^ static_cast<uint64_t>(-(l < 0))')
    after = after.replace('(ul >> 1) ^ -(ul & 1)',
                          'static_cast<int64_t>(ul >> 1) ^ -static_cast<int64_t>(ul & 1)')
    if before != after:
        path.write_text(after, encoding='utf-8')
        print(name)
