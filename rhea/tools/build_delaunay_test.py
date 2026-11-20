"""Builds rhea/tools/delaunay_test.cc (the checks of rhea/delaunay.h) with XPU2's native build.

    python build_delaunay_test.py <worktree root> <output folder>

Prints the test's path; run it, it prints JSON lines and exits non-zero on a failed check.
"""
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
x = root / 'xpu2' / 'interactive'
sys.path.insert(0, str(x))
from native_build import build_units  # noqa: E402

out = Path(sys.argv[2])
inc = [root / 'rhea', x, root / 'toolchain/xpu/optix-dev/include', root / 'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include']
exe, log = build_units(root, [root / 'rhea' / 'tools' / 'delaunay_test.cc'], out, [], ['-I' + str(i) for i in inc])
print(exe)
