// Exercise the internal ISPC function-pointer ABI used by MoonRay shading.
uniform int maskedSum(uniform int a, uniform int b, uniform int c,
                      uniform int d, uniform int e, uniform int f)
{
    return reduce_add(programIndex + a) + b + c + d + e + f;
}
export void * uniform getMaskedSum() { return maskedSum; }
