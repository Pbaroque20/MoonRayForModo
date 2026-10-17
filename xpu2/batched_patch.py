"""Bounded native sample windows; preserve per-lane sampler and contribution order."""
from xpu2.deferred_patch import once

def sampler(text,collect):
    declarations='\n'.join('extern "C" void '+name+'();' for name in
        ('xpu2BatchedSampleEnd','xpu2BatchedLightBegin','xpu2BatchedLightEnd'))
    declarations+='\nextern "C" void xpu2BatchedBegin(uniform int slot);\n'
    declarations+='extern "C" uniform int xpu2BatchedWidth();\n'
    declarations+='extern "C" void xpu2BatchedCollect(uniform float post[], uniform int mask, uniform int slot);\n'
    start=text.index('void\ndrawBsdfSamples(');end=text.index('\nvoid chooseLightsToSample(',start)
    body=text[start:end]
    loop='        uniform int s = bSampler.mLobeToSampleIndex[lobeIndex];\n\n        // Loop over each lobe\'s samples\n        for (int i = 0; i < lobeSampleCount; ++i, ++s) {\n'
    lo=body.index(loop)
    tail='        }\n    }\n}\n'
    hi=body.rindex(tail)
    inner=body[lo+len(loop):hi]
    cut=inner.index('            integrateBsdfSample(')
    prepare=inner[:cut];finish=inner[cut:]
    anchor='            bool isValid = BsdfSampler_sample(pbrTls, &bSampler, lobeIndex,\n                    bsdfSample[0], bsdfSample[1], bsmp[s]);'
    prepare=once(prepare,anchor,'            xpu2BatchedBegin(slot);\n'+anchor+'\n            xpu2BatchedSampleEnd();\n            valid[slot]=isValid;')
    prepare=once(prepare,'            if (!isValid) {\n                continue;\n            }','            if (isValid) {')
    anchor='            LightSetSampler_intersectAndEval(&lSampler, pbrTls, shadingTls, P, cullingNormal, bsmp[s].wi,'
    prepare=once(prepare,anchor,'            xpu2BatchedLightBegin();\n'+anchor)
    anchor='                                             BsdfLobe_getLightSet(lobe), parentLobeLightSets);'
    prepare=once(prepare,anchor,anchor+'\n            xpu2BatchedLightEnd();\n            contributions[slot]=lCo;\n            }')
    window="""        const uniform int base = bSampler.mLobeToSampleIndex[lobeIndex];
        const uniform int maxSamples = reduce_max(lobeSampleCount);
        const uniform int width = xpu2BatchedWidth();
        varying bool valid[16];
        varying LightContribution contributions[16];
        for (uniform int first=0; first<maxSamples; first+=width) {
            const uniform int count=min(width,maxSamples-first);
            // Prepare samples and light evaluations in the original order.
            for (uniform int slot=0; slot<count; ++slot) {
                const varying int i=first+slot;
                const uniform int s=base+first+slot;
                if (i>=lobeSampleCount) { continue; }
""" + prepare + """
            }
            // Collect in the original sample order. No CPU-native pointer is
            // passed to the worker; light records stay in this live stack.
            for (uniform int slot=0; slot<count; ++slot) {
                const varying int i=first+slot;
                const uniform int s=base+first+slot;
                if (i>=lobeSampleCount) { continue; }
""" + collect + """
                lCo=contributions[slot];
""" + finish + """
            }
        }
"""
    return declarations+text[:start]+body[:lo]+window+body[hi+len('        }\n'):]+text[end:]

def lambert(text,hook):
    declaration='extern "C" void xpu2BatchedLambert(uniform float input[], uniform float output[], uniform int lanes[], uniform int count);\n'
    hook=once(hook,'    xpu2NativeLambert(input, output, count);','    xpu2BatchedLambert(input, output, lanes, count);')
    return declaration+once(text,'    return LambertBsdfLobe_eval(lobe, slice, wi, &pdf);',hook)
