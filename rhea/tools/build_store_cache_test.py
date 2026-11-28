"""Builds rhea/tools/store_cache_test.cc (the radiance cache written and read back, rhea/object_warp.h) with XPU2's native build.

    python build_store_cache_test.py <worktree root> <output folder>

Prints the test's path; run it, it prints JSON lines and exits non-zero on a failed check.
"""
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
x = root / 'xpu2' / 'interactive'
sys.path.insert(0, str(x))
from native_build import build_units  # noqa: E402

out = Path(sys.argv[2])
# As xpu2/interactive/build_session.py: the store includes XPU2's CPU tracer, which includes MoonRay's LPE and display
# filter headers.
inc = [root / 'rhea', x, root / 'toolchain/xpu/optix-dev/include', root / 'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include',
       root / 'upstream/openmoonray/moonray/moonray/lib/rendering/lpe', root / 'upstream/openmoonray/moonray/moonray/lib/rendering/displayfilter',
       root / 'build/native-renderer-avx/moonray/lib/rendering/displayfilter', root / 'upstream/openmoonray/moonray/moonray/lib',
       root / 'toolchain/msys64/ucrt64/include/Imath', root / 'toolchain/msys64/ucrt64/include/OpenEXR', root / 'upstream/meshoptimizer/src']
exe, log = build_units(root, [root / 'rhea' / 'tools' / 'store_cache_test.cc'], out, [], ['-I' + str(i) for i in inc])
print(exe)
