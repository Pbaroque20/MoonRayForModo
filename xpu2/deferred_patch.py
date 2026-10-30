"""Guarded native-source patch for a stack-resident, split-phase shading probe."""
def once(text,old,new):
    if text.count(old)!=1:raise ValueError('Unknown native boundary: '+old[:70])
    return text.replace(old,new,1)

def sampler(text,collect):
    declarations='\n'.join('extern "C" void '+name+'();' for name in
        ('xpu2DeferredBegin','xpu2DeferredSampleEnd','xpu2DeferredLightBegin','xpu2DeferredLightEnd'))
    declarations+='\nextern "C" void xpu2DeferredCollect(uniform float post[], uniform int mask);\n'
    # Restrict replacements to drawBsdfSamples; other routines keep their order.
    start=text.index('void\ndrawBsdfSamples(');end=text.index('\nvoid chooseLightsToSample(',start)
    body=text[start:end]
    anchor='            bool isValid = BsdfSampler_sample(pbrTls, &bSampler, lobeIndex,\n                    bsdfSample[0], bsdfSample[1], bsmp[s]);'
    body=once(body,anchor,'            xpu2DeferredBegin();\n'+anchor+'\n            xpu2DeferredSampleEnd();')
    body=once(body,'            if (!isValid) {\n                continue;\n            }','            if (isValid) {')
    anchor='            LightSetSampler_intersectAndEval(&lSampler, pbrTls, shadingTls, P, cullingNormal, bsmp[s].wi,'
    body=once(body,anchor,'            xpu2DeferredLightBegin();\n'+anchor)
    anchor='                                             BsdfLobe_getLightSet(lobe), parentLobeLightSets);'
    body=once(body,anchor,anchor+'\n            xpu2DeferredLightEnd();\n            }\n'+collect)
    return declarations+text[:start]+body+text[end:]

def lambert(text,hook):
    declaration='extern "C" void xpu2DeferredLambert(uniform float input[], uniform float output[], uniform int lanes[], uniform int count);\n'
    hook=once(hook,'    xpu2NativeLambert(input, output, count);','    xpu2DeferredLambert(input, output, lanes, count);')
    return declaration+once(text,'    return LambertBsdfLobe_eval(lobe, slice, wi, &pdf);',hook)
