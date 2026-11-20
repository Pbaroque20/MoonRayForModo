"""MoonRay's iridescence, as MoonLightIPR draws it: the colour DwaBaseMaterial's iridescence tints its specular or clear
coat reflection with, worked out here as a table the GPU reads by angle.

MoonRay's IridescenceBsdfLobe (BsdfIridescence.h) multiplies the lobe it wraps by a colour that depends on the angle
alone: an index, |1 - cos|^exponent * thickness wrapped into 0 to 1, picks it from the hue wheel between the primary and
secondary colours, or from a ramp; then it is blended from white by strength * lerp(at 90, at 0, cos). Everything but
the index's own reckoning and that last blend is a function of the index, so it is tabulated here, IRIDESCENCE_STEPS
colours from index 0 to 1, by MoonRay's own formulas (its ColorSpace.cc and RampControl.cc, followed line by line).
"""
import math

# Keep in step with moonlightipr/src/device/shared.h IRIDESCENCE_STEPS.
IRIDESCENCE_STEPS = 512
# MoonRay's ramps keep their first ten points (RampControl.isph RAMP_MAX_POINTS, DWABASE_MAX_IRIDESCENCE_RAMP_POINTS).
RAMP_MAX_POINTS = 10
EPSILON = 1.1920929e-07     # MoonRay's isZero and isEqual: float's own epsilon
APPLY_SPECULAR, APPLY_COAT = 0, 1
NONE, LINEAR, EXPONENTIAL_UP, EXPONENTIAL_DOWN, SMOOTH, CATMULL_ROM, MONOTONE_CUBIC = range(7)
SPACE_RGB, SPACE_HSV, SPACE_HSL = 0, 1, 2


def _zero(x):
    return abs(x) <= EPSILON


def _equal(a, b):
    return abs(a - b) <= EPSILON


def _hue(c, chroma, top):
    if _zero(chroma):
        return 0.0
    r, g, b = c
    h = (g - b) / chroma if top == 0 else 2.0 + (b - r) / chroma if top == 1 else 4.0 + (r - g) / chroma
    h = math.fmod(h * 60.0, 360.0)
    if h < 0:
        h += 360.0
    return h / 360.0


def rgb_to_hue(c):
    """MoonRay's rgbToHue."""
    high, low = max(c), min(c)
    chroma = high - low
    if _zero(chroma):
        return 0.0
    top = 0 if _equal(high, c[0]) else 1 if _equal(high, c[1]) else 2
    return _hue(c, chroma, top)


def _top(c):
    index, high = 0, c[0]
    if c[1] > high:
        index, high = 1, c[1]
    if c[2] > high:
        index = 2
    return index


def rgb_to_hsv(c):
    top = _top(c)
    v, low = c[top], min(c)
    if _zero(v):
        return [0.0, 0.0, v]
    chroma = v - low
    return [_hue(c, chroma, top), chroma / v, v]


def rgb_to_hsl(c):
    top = _top(c)
    high, low = c[top], min(c)
    l = (high + low) * 0.5
    chroma = high - low
    if _zero(chroma):
        return [0.0, 0.0, l]
    if l > 0.5:
        s = 1.0 if _equal(high + low, 2.0) else abs(chroma / (2.0 - high - low))
    else:
        s = chroma if high + low <= 0 else chroma / (high + low)
    return [_hue(c, chroma, top), s, l]


def _sector(h):
    h = math.fmod(h, 1.0)
    if h < 0:
        h += 1.0
    hue = h * 360.0
    if _equal(hue, 360.0):
        hue = 0.0
    hue /= 60.0
    sector = int(hue)
    return sector, hue - sector


def hsv_to_rgb(c):
    h, s, v = c
    if _zero(s):
        return [v, v, v]
    sector, f = _sector(h)
    p, q, t = v * (1.0 - s), v * (1.0 - s * f), v * (1.0 - s * (1.0 - f))
    return {0: [v, t, p], 1: [q, v, p], 2: [p, v, t], 3: [p, q, v], 4: [t, p, v], 5: [v, p, q]}.get(sector, [p, p, p])


def hsl_to_rgb(c):
    h, s, l = c
    if _zero(s):
        return [l, l, l]
    sector, f = _sector(h)
    if l < 0.5:
        p, w, q, t = l * (1.0 - s), l * (1.0 + s), l * (s * (1.0 - 2.0 * f) + 1.0), l * (s * (2.0 * f - 1.0) + 1.0)
    else:
        p, w = l * (1.0 + s) - s, l * (1.0 - s) + s
        q = l * (1.0 + s * (2.0 * f - 1.0)) + s * (1.0 - 2.0 * f)
        t = l * (1.0 + s * (1.0 - 2.0 * f)) + s * (2.0 * f - 1.0)
    return {0: [w, t, p], 1: [q, w, p], 2: [p, w, t], 3: [p, q, w], 4: [t, p, w], 5: [w, p, q]}.get(sector, [p, p, p])


def hue_to_rgb(hue):
    return hsv_to_rgb([hue, 1.0, 1.0])


def _sign(x):
    return 1 if x > 0 else -1 if x < 0 else 0


def _slope(i0, o0, i1, o1):
    return 0.0 if i0 == i1 else (o1 - o0) / (i1 - i0)


def _monotone(i, o, end):
    """MoonRay's computeFKMonotonoSlope (Fritsch and Carlson), one channel."""
    delta2 = _slope(i[2], o[2], i[3], o[3]) if end not in (2, 3) else 0.0
    delta1 = _slope(i[1], o[1], i[2], o[2]) if end != 3 else 0.0
    delta0 = _slope(i[0], o[0], i[1], o[1]) if end not in (1, 3) else 0.0
    if _zero(delta1):
        return 0.0, 0.0
    if end == 1:
        s1, s2 = delta1, (delta2 + delta1) / 2.0 if _sign(delta1) == _sign(delta2) else 0.0
    elif end == 2:
        s1, s2 = (delta0 + delta1) / 2.0 if _sign(delta0) == _sign(delta1) else 0.0, delta1
    else:
        s1 = (delta0 + delta1) / 2.0 if _sign(delta0) == _sign(delta1) else 0.0
        s2 = (delta2 + delta1) / 2.0 if _sign(delta1) == _sign(delta2) else 0.0
    alpha, beta = s1 / delta1, s2 / delta1
    if alpha >= 0 and beta >= 0 and alpha * alpha + beta * beta > 9.0:
        tau = 3.0 / math.sqrt(alpha * alpha + beta * beta)
        s1, s2 = tau * s1, tau * s2
    return s1, s2


class ColorRamp:
    """MoonRay's ColorRampControl, as IridescenceBsdfLobe sets it up (its hue blend adjustment on)."""

    def __init__(self, positions, colours, interpolators, space):
        count = min(len(positions), len(colours), len(interpolators), RAMP_MAX_POINTS)
        points = [(float(positions[i]), [float(c) for c in colours[i]], int(interpolators[i])) for i in range(count)]
        if any(points[i][0] > points[i + 1][0] for i in range(count - 1)):
            points.sort(key=lambda point: point[0])
        self.inputs = [p[0] for p in points]
        self.outputs = [p[1] for p in points]
        self.modes = [p[2] for p in points]
        self.slopes = [[0.0, 0.0, 0.0] for _ in points]
        if MONOTONE_CUBIC in self.modes:
            n = count
            index = 0
            while index < n - 1:
                k0, k1, k2, k3, end = index - 1, index, index + 1, index + 2, 0
                if index == 0:
                    k0, end = k1, 1
                if index + 1 == n - 1:
                    k3, end = k2, 3 if end == 1 else 2
                for c in range(3):
                    s1, s2 = _monotone([self.inputs[k] for k in (k0, k1, k2, k3)], [self.outputs[k][c] for k in (k0, k1, k2, k3)], end)
                    self.slopes[k1][c], self.slopes[k2][c] = s1, s2
                index += 2
            if index == n - 1:
                last = n - 1
                self.slopes[last] = [_slope(self.inputs[last - 1], self.outputs[last - 1][c], self.inputs[last], self.outputs[last][c]) for c in range(3)]
        # Catmull-Rom blends are made in RGB: HSV's wrap round the hue wheel is not worked out for four points.
        self.space = SPACE_RGB if space in (SPACE_HSV, SPACE_HSL) and CATMULL_ROM in self.modes else space
        if self.space == SPACE_HSV:
            self.outputs = [rgb_to_hsv(o) for o in self.outputs]
        elif self.space == SPACE_HSL:
            self.outputs = [rgb_to_hsl(o) for o in self.outputs]

    def _cubic(self, interval, t, mode):
        n = len(self.inputs)
        k = [interval - 1 if interval else interval, interval, 0, 0]
        if interval == n - 2:
            k[2] = k[3] = interval + 1
        elif interval == n - 1:
            k[2] = k[3] = interval
            t = 0.0
        else:
            k[2], k[3] = interval + 1, interval + 2
        p = [self.outputs[i] for i in k]
        if mode == CATMULL_ROM:
            t2, t3 = t * t, t * t * t
            # 0.5 * (1, t, t^2, t^3) times MoonRay's Catmull-Rom matrix, dotted with the four points.
            w = [0.5 * (-t + 2 * t2 - t3), 0.5 * (2 - 5 * t2 + 3 * t3), 0.5 * (t + 4 * t2 - 3 * t3), 0.5 * (-t2 + t3)]
            return [sum(w[j] * p[j][c] for j in range(4)) for c in range(3)]
        x1, x2 = self.inputs[k[1]], self.inputs[k[2]]
        h, t2, t3 = x2 - x1, t * t, t * t * t
        h00, h10, h01, h11 = 2 * t3 - 3 * t2 + 1, t3 - 2 * t2 + t, -2 * t3 + 3 * t2, t3 - t2
        return [h00 * p[1][c] + h * h10 * self.slopes[k[1]][c] + h01 * p[2][c] + h * h11 * self.slopes[k[2]][c] for c in range(3)]

    def _raw(self, t):
        n = len(self.inputs)
        left, right = 0, n - 1
        if t < self.inputs[left]:
            return list(self.outputs[0])
        if t > self.inputs[right]:
            return list(self.outputs[n - 1])
        while right - left > 1:
            middle = (left + right) // 2
            if self.inputs[middle] > t:
                right = middle
            else:
                left = middle
        span = self.inputs[right] - self.inputs[left]
        if _zero(span):
            return list(self.outputs[left])
        t = (t - self.inputs[left]) / span
        mode = self.modes[left]
        if mode in (CATMULL_ROM, MONOTONE_CUBIC):
            return self._cubic(left, t, mode)
        weight = 0.0 if mode == NONE else t if mode == LINEAR else t * t if mode == EXPONENTIAL_UP \
            else 1.0 - (1.0 - t) ** 2 if mode == EXPONENTIAL_DOWN else math.sin(t * math.pi / 2) if mode == SMOOTH else 0.0
        a, b = list(self.outputs[left]), list(self.outputs[right])
        if self.space in (SPACE_HSV, SPACE_HSL):
            # The shortest way round the hue wheel.
            if (a[0] + 1.0) - b[0] < 0.5:
                a[0] += 1.0
            elif (b[0] + 1.0) - a[0] < 0.5:
                b[0] += 1.0
        return [u + weight * (v - u) for u, v in zip(a, b)]

    def __call__(self, t):
        if not self.inputs:
            return [0.0, 0.0, 0.0]
        result = self._raw(t)
        if self.space == SPACE_HSV:
            return hsv_to_rgb(result)
        if self.space == SPACE_HSL:
            return hsl_to_rgb(result)
        return result


def _fit(value, old_low, old_high, new_low, new_high):
    span = old_high - old_low
    return new_low if _zero(span) else (new_high - new_low) * (value - old_low) / span + new_low


def hue_colour(index, primary, secondary, flip):
    """MoonRay's computeIridescenceColor, from the index on: a colour from the hue wheel between the two colours."""
    if all(_equal(a, b) for a, b in zip(primary, secondary)):
        if flip:
            return list(primary)
        start = rgb_to_hue(primary)
        return hue_to_rgb(_fit(index, 0.0, 1.0, start, start + 1.0))
    first, second = rgb_to_hue(primary), rgb_to_hue(secondary)
    if second < first and not flip:
        second += 1.0
    elif first < second and flip:
        first += 1.0
    back = 1.0 / (abs(second - first) / 0.166667 + 1.0)
    spectrum = 1.0 - back
    if index < spectrum:
        return hue_to_rgb(_fit(index, 0.0, spectrum, first, second))
    a, b = hue_to_rgb(second), hue_to_rgb(first)
    w = (index - spectrum) / back
    return [u + w * (v - u) for u, v in zip(a, b)]


def surface(get, note, has_specular, has_coat):
    """A Dwa material's iridescence as MoonLightIPR draws it, or None where it has none to show: the lobe it tints, the
    numbers that work out the index and the blend, and the colours from index 0 to 1."""
    strength = min(1.0, max(0.0, float(get('iridescence', 0.0))))
    if strength <= 0.0:
        return None
    apply = APPLY_COAT if int(get('iridescence_apply_to', 0)) == 1 else APPLY_SPECULAR
    if not (has_coat if apply == APPLY_COAT else has_specular):
        return None
    from .working_space import color as working_color
    def colour(key):
        # MoonRay is given its Rgb attributes in the working space (shader_library.emit), and clamps them; a
        # ramp's colours, an RgbVector, it is given as they are. The table is in the working space, and the GPU takes
        # it as it is.
        return [min(1.0, max(0.0, float(c))) for c in working_color([float(v) for v in get(key, [1.0, 0.0, 0.0])])]
    if int(get('iridescence_color_control', 0)) == 1:
        ramp = ColorRamp(list(get('iridescence_positions', [])), list(get('iridescence_colors', [])),
                         list(get('iridescence_interpolations', [])), int(get('iridescence_ramp_interpolation_mode', 0)))
        pick = ramp
    else:
        primary, secondary = colour('iridescence_primary_color'), colour('iridescence_secondary_color')
        flip = bool(get('iridescence_flip_hue_direction', False))
        pick = lambda index: hue_colour(index, primary, secondary, flip)  # noqa: E731
    table = [c for i in range(IRIDESCENCE_STEPS) for c in pick(i / (IRIDESCENCE_STEPS - 1))]
    return {'apply': apply, 'strength': strength,
            'exponent': max(0.0, float(get('iridescence_exponent', 1.0))),
            'thickness': max(0.0, float(get('iridescence_thickness', 1.0))),
            'at0': min(1.0, max(0.0, float(get('iridescence_at_0_incidence', 1.0)))),
            'at90': min(1.0, max(0.0, float(get('iridescence_at_90_incidence', 1.0)))),
            'table': table}
