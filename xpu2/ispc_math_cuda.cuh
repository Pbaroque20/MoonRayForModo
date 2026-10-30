// Adapted from ISPC v1.31.0 stdlib.ispc varying sincos.
// Copyright (c) 2010-2026, Intel Corporation. SPDX-License-Identifier: BSD-3-Clause
// See ISPC_MATH_LICENSE.txt. Restricted here to Lambert phi in [0, 2*pi].
__device__ void ispcSincos(float x_full,float* sin_result,float* cos_result) {
        const float pi_over_two_vec = 1.57079637050628662109375f;
        const float two_over_pi_vec = 0.636619746685028076171875f;
        float scaled = x_full * two_over_pi_vec;
        float k_real = floorf(scaled);
        int k = (int)k_real;

        // Reduced range version of x
        float x = x_full - k_real * pi_over_two_vec;
        int k_mod4 = k & 3;
        bool cos_usecos = (k_mod4 == 0 || k_mod4 == 2);
        bool sin_usecos = (k_mod4 == 1 || k_mod4 == 3);
        bool sin_flipsign = (k_mod4 > 1);
        bool cos_flipsign = (k_mod4 == 1 || k_mod4 == 2);

        const float one_vec = 1.f;
        const float sin_c2 = -0.16666667163372039794921875f;
        const float sin_c4 = 8.333347737789154052734375e-3f;
        const float sin_c6 = -1.9842604524455964565277099609375e-4f;
        const float sin_c8 = 2.760012648650445044040679931640625e-6f;
        const float sin_c10 = -2.50293279435709337121807038784027099609375e-8f;

        const float cos_c2 = -0.5f;
        const float cos_c4 = 4.166664183139801025390625e-2f;
        const float cos_c6 = -1.388833043165504932403564453125e-3f;
        const float cos_c8 = 2.47562347794882953166961669921875e-5f;
        const float cos_c10 = -2.59630184018533327616751194000244140625e-7f;

        float x2 = x * x;

        float sin_formula = x2 * sin_c10 + sin_c8;
        float cos_formula = x2 * cos_c10 + cos_c8;
        sin_formula = x2 * sin_formula + sin_c6;
        cos_formula = x2 * cos_formula + cos_c6;

        sin_formula = x2 * sin_formula + sin_c4;
        cos_formula = x2 * cos_formula + cos_c4;

        sin_formula = x2 * sin_formula + sin_c2;
        cos_formula = x2 * cos_formula + cos_c2;

        sin_formula = x2 * sin_formula + one_vec;
        cos_formula = x2 * cos_formula + one_vec;

        sin_formula *= x;

        *sin_result = sin_usecos ? cos_formula : sin_formula;
        *cos_result = cos_usecos ? cos_formula : sin_formula;

        *sin_result = sin_flipsign ? -*sin_result : *sin_result;
        *cos_result = cos_flipsign ? -*cos_result : *cos_result;
}
