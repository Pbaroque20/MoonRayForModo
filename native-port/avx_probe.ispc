export void moonray_probe_shift(uniform const int values[], uniform int output[], uniform int count)
{
    foreach (i = 0 ... count) {
        output[i] = values[i] >> 23;
    }
}
