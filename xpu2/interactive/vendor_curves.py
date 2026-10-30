"""Writes curve_embree.h: MoonRay XPU's curve intersection code (OptixGPUMath.h's vector and curve functions, and the
Embree 4 code MoonRay ported for round curves), unchanged but for the device qualifiers, so the same code compiles
for the CPU lane and the GPU lane.

vendor_curves.py <MoonRay source: the openmoonray/moonray folder>"""
import re
import sys
from pathlib import Path

SRC = Path(sys.argv[1]) / 'moonray' / 'lib' / 'rendering' / 'rt' / 'gpu' / 'optix'
OUT = Path(__file__).resolve().parent / 'curve_embree.h'


def qualifiers(text):
    text = text.replace('inline __host__ __device__', 'X2_HD inline')
    text = text.replace('static inline __device__', 'static X2_HD inline')
    text = text.replace('inline __device__', 'X2_HD inline')
    text = text.replace('__host__ __device__', 'X2_HD inline')
    text = re.sub(r'^__device__\n', 'X2_HD inline\n', text, flags=re.M)
    text = re.sub(r'^(\s+)__device__\n', r'\1X2_HD\n', text, flags=re.M)
    text = re.sub(r'^(\s+)__device__ ', r'\1X2_HD ', text, flags=re.M)
    assert '__device__' not in text.replace('constexpr __device__', ''), [l for l in text.splitlines() if '__device__' in l][:5]
    return text


def strip(text):
    text = re.sub(r'^#include .*\n', '', text, flags=re.M)
    text = re.sub(r'^#pragma once\n', '', text, flags=re.M)
    return text


math = (SRC / 'OptixGPUMath.h').read_text(encoding='utf-8')
start = math.index('// Extended versions of clamp/min/max')
end = math.index('// Affine transform')
body = math[start:end]
# The host already has rsqrtf from the shim; OptiX's boxes and the curve enums are not used here.
for name in ('emptyAabb', 'expandAabb', 'combineAabbs'):
    m = re.search(r'inline __host__ __device__\nOptixAabb ' + name + r'\(.*?\n}\n', body, flags=re.S)
    assert m, name
    body = body.replace(m.group(0), '')
m = re.search(r'// Curve functions\n\nenum CurveType\n{.*?};\n\nenum CurveSubType\n{.*?};\n', body, flags=re.S)
assert m
body = body.replace(m.group(0), '// Curve functions\n')
xform = math[end:]
xs = xform.index('struct OptixGPUXform')
xe = xform.index('} // namespace rt')
xform = xform[xs:xe]
m = re.search(r'    __host__ __device__\n    OptixAabb transformAabb\(.*?\n    }\n\n', xform, flags=re.S)
assert m
xform = xform.replace(m.group(0), '')
math_part = qualifiers(body) + '\n' + qualifiers(xform)

support = strip((SRC / 'EmbreeSupport.h').read_text(encoding='utf-8'))
old_inf = support[support.index('#if defined(__CUDACC_RTC__)'):support.index('struct EmbreeRayHit')]
support = support.replace(old_inf, '''// (pos_inf, inf, neg_inf, ulp and min_rcp_input: curve_core.h's macros, undefined after this file)

''')
support = qualifiers(support)
roundline = qualifiers(strip((SRC / 'EmbreeRoundlineIntersector.h').read_text(encoding='utf-8')))
bspline = qualifiers(strip((SRC / 'EmbreeBsplineCurve.h').read_text(encoding='utf-8')))
sweep = qualifiers(strip((SRC / 'EmbreeCurveIntersectorSweep.h').read_text(encoding='utf-8')))

header = '''// MoonRay XPU's curve intersection code, for both lanes: from MoonRay's
// lib/rendering/rt/gpu/optix (OptixGPUMath.h's vector and curve functions and
// OptixGPUXform; EmbreeSupport.h, EmbreeRoundlineIntersector.h,
// EmbreeBsplineCurve.h and EmbreeCurveIntersectorSweep.h, which MoonRay took
// from Embree 4). Apache-2.0: Copyright 2009-2021 Intel Corporation; Copyright
// 2023-2024 DreamWorks Animation LLC. See MOONRAY_LICENSE.txt. Written by
// vendor_curves.py: only the device qualifiers (X2_HD), the includes, the
// constants and OptiX's bounding boxes are changed. Included by curve_core.h
// inside its namespace, after the vector types; not a header of its own.
'''
OUT.write_text(header + '\n' + math_part + '\n' + support + '\n' + roundline + '\n' + bspline + '\n' + sweep, encoding='utf-8')
print(OUT, len(OUT.read_text().splitlines()), 'lines')
