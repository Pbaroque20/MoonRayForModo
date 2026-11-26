// environment_layers.texture's blend, for the plugin's Python: an environment's layers, bottom first, laid over one
// another in every direction of a latitude/longitude map, as its Python loop lays them (the same arithmetic in
// doubles, the same order). Done here over the machine's threads with Python's lock let go: in Python a car's
// four-layer environment took 15 s of a scene's first preview. Only layers without groups or masks: image (its pixels
// already shrunk to the map's size, and its alpha), colour, and Modo's sky gradients; any other layer is Python's.
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <thread>
#include <vector>

namespace {

const double PI=3.14159265358979323846;

// environment_layers.blend's modes, by their place in MODES (environment_layers.py).
enum Mode {Normal,Multiply,Add,Subtract,Screen,Divide,Difference,Darken,Lighten,Overlay,Hardlight,Exclusion,Softlight,Colordodge,Colorburn};

double component(int mode,double a,double b) {
    switch(mode) {
        case Normal: return b;
        case Multiply: return a*b;
        case Add: return a+b;
        case Subtract: return a-b;
        case Screen: return 1-(1-a)*(1-b);
        case Divide: return a/std::max(1e-6,b);
        case Difference: return std::fabs(a-b);
        case Darken: return std::min(a,b);
        case Lighten: return std::max(a,b);
        case Overlay: return a<.5?2*a*b:1-2*(1-a)*(1-b);
        case Hardlight: return b<.5?2*a*b:1-2*(1-a)*(1-b);
        case Exclusion: return a+b-2*a*b;
        case Softlight: {
            const double d=a<=.25?((16*a-12)*a+4)*a:std::sqrt(std::max(0.0,a));
            return b<=.5?a-(1-2*b)*a*(1-a):a+(2*b-1)*(d-a);
        }
        case Colordodge: return b>=1?1:std::min(1.0,a/std::max(1e-6,1-b));
        case Colorburn: return b<=0?0:1-std::min(1.0,(1-a)/std::max(1e-6,b));
    }
    return b;
}

// environments.gradient_color: kind 0 constant, 1 overcast, 2 two colours, 3 four colours. g: zenith, sky, ground,
// nadir (3 each), the sky's and the ground's exponents.
void gradient(int kind,const double* g,double height,double* out) {
    height=std::max(-1.0,std::min(1.0,height));
    const double* zenith=g; const double* sky=g+3; const double* ground=g+6; const double* nadir=g+9;
    if(kind==0) { for(int k=0;k<3;++k) out[k]=zenith[k]; return; }
    if(kind==1) {
        for(int k=0;k<3;++k) out[k]=height>=0?zenith[k]*(1+2*height)/3:nadir[k];
        return;
    }
    const double *a,*b; double t;
    if(kind==2) { a=nadir; b=zenith; t=(height+1)/2; }
    else if(height>=0) { a=sky; b=zenith; t=1-std::pow(1-height,std::max(.001,g[12])); }
    else { a=ground; b=nadir; t=1-std::pow(1+height,std::max(.001,g[13])); }
    for(int k=0;k<3;++k) out[k]=a[k]+(b[k]-a[k])*t;
}

// daylight.color: Modo's physical sky in a direction, from the table daylight.sky blends for the sun's height and the
// haze (16 heights by 24 angles from the sun, 3 numbers each). s: the sun's direction (3, as given), the table's clamp
// scale, normalize (1 or 0), the sky's gamma, whether the ground's colour moves the sky (1 or 0), the ground's colour
// (3); then the table.
const int ALTITUDE_COUNT = 16, ANGLE_COUNT = 24;
const double HORIZON_BLEND = 0.5, GROUND_BOUNCE[3] = {.75, .46, .49};

void physical_sky(const double* direction, const double* s, double* out) {
    const double* ground = s + 7;
    const double* values = s + 10;
    if (direction[1] < 0) {
        const double below = std::asin(std::min(1.0, -direction[1]));
        const double flat = std::hypot(direction[0], direction[2]);
        if (below >= HORIZON_BLEND || flat <= 0) { for (int k = 0; k < 3; ++k) out[k] = ground[k]; return; }
        const double level[3] = {direction[0] / flat, 0.0, direction[2] / flat};
        double horizon[3];
        physical_sky(level, s, horizon);
        for (int k = 0; k < 3; ++k) out[k] = ground[k] + (horizon[k] - ground[k]) * (1 - below / HORIZON_BLEND);
        return;
    }
    double sun[3] = {s[0], s[1], s[2]};
    const double length = std::sqrt(sun[0] * sun[0] + sun[1] * sun[1] + sun[2] * sun[2]);
    for (double& v : sun) v /= length;
    const double degrees = 180.0 / PI;
    const double altitude = std::asin(std::max(0.0, std::min(1.0, direction[1]))) * degrees;
    const double apart = std::acos(std::max(-1.0, std::min(1.0, direction[0] * sun[0] + direction[1] * sun[1] + direction[2] * sun[2]))) * degrees;
    const double i = (ALTITUDE_COUNT - 1) * std::sqrt(altitude / 90.0), j = (ANGLE_COUNT - 1) * std::sqrt(apart / 180.0);
    const int i0 = std::min(ALTITUDE_COUNT - 2, int(i)), j0 = std::min(ANGLE_COUNT - 2, int(j));
    const double fi = i - i0, fj = j - j0;
    const int width = ANGLE_COUNT * 3, a = i0 * width + j0 * 3, b = (i0 + 1) * width + j0 * 3;
    for (int c = 0; c < 3; ++c)
        out[c] = (values[a + c] * (1 - fj) + values[a + 3 + c] * fj) * (1 - fi) + (values[b + c] * (1 - fj) + values[b + 3 + c] * fj) * fi;
    if (s[6] != 0)
        for (int c = 0; c < 3; ++c)
            out[c] = out[c] * (1 - .5 * GROUND_BOUNCE[c]) / std::max(.05, 1 - std::min(1.0, std::max(0.0, ground[c])) * GROUND_BOUNCE[c]);
    if (s[4] != 0 && s[3] > 0) {
        const double gamma = std::max(.01, s[5]);
        for (int c = 0; c < 3; ++c) out[c] = std::pow(std::max(0.0, out[c] / s[3]), 1.0 / gamma);
    }
}

// environment_projections.py's coordinates and tiled, for a layer laid by one of Modo's Texture Locator projections
// (MR_environment_projected): p, its 22 numbers (environment_projections.numbers): kind (1 planar, 2 cylindrical,
// 3 spherical, 4 cubic, 5 box, 6 light probe, 7 triplanar, 8 one colour), axis, the locator's turn (9, rows of unit
// length), its size (3), the wraps (2), cos and sin of the UV rotation, the repeat modes (0 repeat, 1 reset, 2 mirror,
// 3 edge), the blending hardness. Writes up to three (u, v, weight); returns how many.
const int PROJECTION_SIZE = 22;

void turned_about_middle(double u, double v, double c, double s, double* out) {
    u -= .5; v -= .5;
    out[0] = u * c - v * s + .5;
    out[1] = u * s + v * c + .5;
}

int projected(const double* p, const double* d, double out[3][3]) {
    const int kind = int(p[0]);
    const int axis = std::max(0, std::min(2, int(p[1])));
    const double* t = p + 2;
    const double* s = p + 11;
    const double c = p[16], sn = p[17];
    static const int order[3][3] = {{2, 1, 0}, {0, 2, 1}, {0, 1, 2}};
    const int* o = order[axis];
    if (kind == 8) { out[0][0] = 0; out[0][1] = 0; out[0][2] = 1; return 1; }
    double q[3];
    for (int i = 0; i < 3; ++i) q[i] = d[0] * t[i * 3] + d[1] * t[i * 3 + 1] + d[2] * t[i * 3 + 2];
    if (kind == 6) {
        // environment_projections.probe_turn: the locator's columns (x, y, z), each made unit length and square to
        // those before; the direction is read along each.
        double g[3][3];
        for (int col = 0; col < 3; ++col) {
            double v[3] = {t[col] * s[0], t[3 + col] * s[1], t[6 + col] * s[2]};
            for (int k = 0; k < col; ++k) {
                const double dot = v[0] * g[k][0] + v[1] * g[k][1] + v[2] * g[k][2];
                for (int i = 0; i < 3; ++i) v[i] -= dot * g[k][i];
            }
            double length = std::sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]); if (length == 0) length = 1e-12;
            for (int i = 0; i < 3; ++i) g[col][i] = v[i] / length;
        }
        double f[3];
        for (int i = 0; i < 3; ++i) f[i] = g[i][0] * d[0] + g[i][1] * d[1] + g[i][2] * d[2];
        const double a = f[o[0]], b = f[o[1]], h = f[o[2]];
        double length = std::sqrt(a * a + b * b + h * h); if (length == 0) length = 1e-12;
        const double across = std::hypot(a, h);
        out[0][2] = 1;
        if (across < 1e-12) { out[0][0] = .5; out[0][1] = .5; return 1; }
        const double r = std::acos(std::max(-1.0, std::min(1.0, -b / length))) / PI;
        out[0][0] = .5 - .5 * a / across * r; out[0][1] = .5 + .5 * h / across * r;
        return 1;
    }
    if (kind == 5) {
        int face = 0;
        for (int i = 1; i < 3; ++i) if (std::fabs(d[i]) > std::fabs(d[face])) face = i;
        const double sign = d[face] >= 0 ? 1 : -1;
        double u, v;
        if (face == 0) { u = -sign * d[1]; v = d[2]; }
        else if (face == 1) { u = sign * d[0]; v = d[2]; }
        else { u = d[0]; v = -sign * d[1]; }
        turned_about_middle(.5 + u / s[0], .5 + v / s[1], c, sn, out[0]); out[0][2] = 1;
        return 1;
    }
    const double l[3] = {q[0] / s[0], q[1] / s[1], q[2] / s[2]};
    if (kind == 1) { turned_about_middle(.5 + l[o[0]], .5 + l[o[1]], c, sn, out[0]); out[0][2] = 1; return 1; }
    if (kind == 2 || kind == 3) {
        const double w[3] = {q[0] / (s[0] * s[0]), q[1] / (s[1] * s[1]), q[2] / (s[2] * s[2])};
        const double a = w[o[0]], b = w[o[1]], h = w[o[2]];
        const double u = .5 + std::atan2(a, b) / (2 * PI);
        double v;
        if (kind == 2) v = (l[o[2]]) * p[15] + .5;   // (0.5 + h - 0.5) * wrap + 0.5
        else {
            double length = std::sqrt(a * a + b * b + h * h); if (length == 0) length = 1e-12;
            v = (.5 + std::asin(std::max(-1.0, std::min(1.0, h / length))) / PI) * p[15];
        }
        turned_about_middle(u * p[14], v, c, sn, out[0]); out[0][2] = 1;
        return 1;
    }
    if (kind == 4) {
        int face = 0;
        for (int i = 1; i < 3; ++i) if (std::fabs(q[i]) > std::fabs(q[face])) face = i;
        const double sign = q[face] >= 0 ? 1 : -1;
        double u, v;
        if (face == 0) { u = sign * l[2]; v = l[1]; }
        else if (face == 1) { u = l[0]; v = sign * l[2]; }
        else { u = -sign * l[0]; v = l[1]; }
        turned_about_middle(.5 + u, .5 + v, c, sn, out[0]); out[0][2] = 1;
        return 1;
    }
    if (kind == 7) {
        const double power = 1 + 25 * std::max(0.0, p[20]);
        double weights[3], total = 0;
        for (int i = 0; i < 3; ++i) { weights[i] = std::pow(std::max(std::fabs(q[i]) - .5, 0.0), power); total += weights[i]; }
        if (total <= 0) {
            int face = 0;
            for (int i = 1; i < 3; ++i) if (std::fabs(q[i]) > std::fabs(q[face])) face = i;
            for (int i = 0; i < 3; ++i) weights[i] = i == face ? 1 : 0;
            total = 1;
        }
        const double planes[3][2] = {{l[2], l[1]}, {l[0], l[2]}, {l[0], l[1]}};
        int n = 0;
        for (int i = 0; i < 3; ++i) {
            if (weights[i] <= 0) continue;
            turned_about_middle(.5 + planes[i][0], .5 + planes[i][1], c, sn, out[n]);
            out[n][2] = weights[i] / total;
            ++n;
        }
        return n;
    }
    return 0;
}

// environment_projections.tiled: false where the coordinate is reset (outside the image).
bool tiled(double& value, int mode) {
    if (mode == 1) return value >= 0 && value <= 1;
    if (mode == 3) { value = std::min(1.0, std::max(0.0, value)); return true; }
    if (mode == 2) { value = std::fmod(value, 2.0); if (value < 0) value += 2.0; if (value > 1) value = 2.0 - value; return true; }
    value = value - std::floor(value);
    return true;
}

// environment_projections.texel.
long long texel(long long index, long long count, int mode) {
    if (mode == 0) { index %= count; return index < 0 ? index + count : index; }
    if (mode == 2) {
        index %= 2 * count; if (index < 0) index += 2 * count;
        return index >= count ? 2 * count - 1 - index : index;
    }
    return std::min(count - 1, std::max(0LL, index));
}

}  // namespace

// procedural_bake.cpp's pattern at one point.
void modo_procedural_point(const double* settings, double u, double v, float* rgb, float* alpha);

namespace {

// procedurals._bias.
double bias(double x, double b) {
    b = std::max(.00001, std::min(.99999, b));
    x = std::max(0.0, std::min(1.0, x));
    return x / ((1 / b - 2) * (1 - x) + 1);
}

double nearest_whole(double x) { return std::fabs(x - std::nearbyint(x)); }

// procedurals.environment_sample: a Grid (kind 0: line 0, square 1, triangle 2, hexagon 3) or Dots (kind 1: square 1,
// hexagon 3) as Modo's renderer lays it in an environment, at the image coordinates (u, v); any other pattern as
// procedural_bake lays it. s: MR_procedural_bake's settings (kind, pattern, width, transition, bias, gain, colour 1,
// colour 2, alpha 1, alpha 2, ...).
void environment_procedural_point(const double* s, double u, double v, float* rgb, float* alpha) {
    const int kind = int(s[0]), pattern = int(s[1]);
    const bool grid = kind == 0 && pattern >= 0 && pattern <= 3, dots = kind == 1 && (pattern == 1 || pattern == 3);
    if (!grid && !dots) { modo_procedural_point(s, u, v, rgb, alpha); return; }
    const double root3 = std::sqrt(3.0);
    static const double centres[6][2] = {{.5, 0.0}, {0.0, .86602540378443865}, {1.0, .86602540378443865},
                                         {.5, 1.7320508075688772}, {-.5, .86602540378443865}, {1.5, .86602540378443865}};
    double distance;
    if (grid && pattern == 1) distance = std::min(nearest_whole(u - .5), nearest_whole(v - .5));
    else if (grid && pattern == 0) distance = nearest_whole(v);
    else if (grid && pattern == 2) {
        const double x = u - std::floor(u), y = (v - .5) - std::floor(v - .5), fold = std::min(y, 1 - y);
        distance = std::min(fold, std::min(std::fabs(x - fold / root3) * root3 / 2, std::fabs(x + fold / root3 - 2 / root3) * root3 / 2));
    } else if (dots && pattern == 1) distance = std::hypot(u - std::nearbyint(u), v - std::nearbyint(v));
    else {
        const double x = u - std::floor(u), y = v - std::floor(v);
        double best = 1e300;
        for (const auto& c : centres) {
            const double dx = std::fabs(x - c[0]), dy = std::fabs(y - c[1]);
            best = std::min(best, dots ? std::hypot(dx, dy) : std::max(dx, .5 * dx + root3 / 2 * dy));
        }
        distance = dots ? best : .5 - best;
    }
    const double half = .5 * std::max(0.0, std::min(1.0, s[2])), transition = std::max(0.0, s[3]);
    double away;
    if (transition <= 1e-9) away = distance > half ? 1.0 : 0.0;
    else { away = std::max(0.0, std::min(1.0, (distance - half) / transition)); away = away * away * (3 - 2 * away); }
    double t = bias(1 - away, s[4]);
    const double g = s[5];
    t = t < .5 ? .5 * bias(2 * t, 1 - g) : 1 - .5 * bias(2 - 2 * t, 1 - g);
    const double low = std::min(s[12], s[13]), high = std::max(s[12], s[13]);
    const double a = std::max(0.0, std::min(1.0, std::min(high, std::max(low, s[12] * t + s[13] * (1 - t)))));
    for (int k = 0; k < 3; ++k) { rgb[k] = float(s[6 + k] * t + s[9 + k] * (1 - t)); alpha[k] = float(a); }
}

}  // namespace

// width x height directions, rows bottom up (the first row looks straight down), as the PFM the Python writes. For each
// of count layers, bottom first: kinds (0 image, 1 colour, 2 gradient), modes (above), opacities, inverts (1 to invert
// its colour); images: its pixels (width*height*3, or null) and alpha (width*height, or null); turns: 9 numbers of
// its inverse placement (row-major, as coordinates.inverse gives a 4x4's top-left), or all zero for none; uv: a, b, c,
// d, e, f, cos(rotation), sin(rotation), scale x, scale y; colours: 3 numbers; gradients: the gradient kind (as above)
// then 14 numbers. out: width*height*3 floats. Returns 0.
static int blend_layers(int width,int height,int count,const int* kinds,const int* modes,
        const double* opacities,const int* inverts,const float* const* images,const float* const* alphas,const double* turns,
        const double* uv,const double* colours,const double* gradients,const double* const* skies,const double* const* patterns,
        const double* projections,float* out,int threads) {
    if(threads<=0) threads=int(std::max(1u,std::thread::hardware_concurrency()));
    auto rows=[&](int begin,int end) {
        for(int y=begin;y<end;++y) {
            const double latitude=((y+.5)/height-.5)*PI;
            for(int x=0;x<width;++x) {
                const double longitude=((x+.5)/width-.5)*2*PI;
                const double direction[3]={std::sin(longitude)*std::cos(latitude),std::sin(latitude),std::cos(longitude)*std::cos(latitude)};
                double colour[3]={0,0,0};
                for(int l=0;l<count;++l) {
                    double foreground[3]={0,0,0},coverage=1.0;
                    if(kinds[l]==1) {
                        for(int k=0;k<3;++k) foreground[k]=colours[l*3+k];
                    } else if(kinds[l]==2) {
                        gradient(int(gradients[l*15]),gradients+l*15+1,direction[1],foreground);
                    } else if(kinds[l]==3) {
                        // As the renderers show it, its columns run the other way (environment_layers.texture).
                        const double mirrored[3]={-direction[0],direction[1],direction[2]};
                        physical_sky(mirrored,skies[l],foreground);
                    } else if(projections&&projections[l*PROJECTION_SIZE]!=0) {
                        // Laid by one of Modo's projections (environment_projections.sample and .procedural).
                        const double* p=projections+l*PROJECTION_SIZE;
                        const int tileU=int(p[18]),tileV=int(p[19]);
                        double at[3][3];
                        // The world's direction: the renderers show this map's columns the other way round
                        // (as a physical sky's, above), and Modo lays its projections by the world's.
                        const double world[3]={-direction[0],direction[1],direction[2]};
                        const int n=projected(p,world,at);
                        const float* pixels=images[l];
                        const float* alpha=alphas[l];
                        double total=0;
                        coverage=0;
                        for(int i=0;i<n;++i) {
                            double u=at[i][0],v=at[i][1];
                            const double weight=at[i][2];
                            if(kinds[l]==4) {
                                // environment_projections.procedural_coordinates: the repeat modes do nothing; UV
                                // Map (one colour for an image, axis 3) at the world's x and z.
                                if(int(p[0])==8) { u=int(p[1])==3?world[0]:0.0; v=int(p[1])==3?world[2]:0.0; }
                                float rgb[3],grey[3];
                                environment_procedural_point(patterns[l],u,v,rgb,grey);
                                for(int k=0;k<3;++k) foreground[k]+=rgb[k]*weight;
                                coverage+=grey[0]*weight;
                                total+=weight;
                                continue;
                            }
                            if(!tiled(u,tileU)||!tiled(v,tileV)) continue;
                            u=u*width-.5; v=v*height-.5;
                            const double fx=std::floor(u),fy=std::floor(v);
                            const double ax=u-fx,ay=v-fy;
                            const long long ix=(long long)fx,iy=(long long)fy;
                            double found[3]={0,0,0},covered=alpha?0.0:1.0;
                            const double weights[4][3]={{0,0,(1-ax)*(1-ay)},{1,0,ax*(1-ay)},{0,1,(1-ax)*ay},{1,1,ax*ay}};
                            for(const auto& w:weights) {
                                const long long index=texel(iy+(long long)w[1],height,tileV)*width+texel(ix+(long long)w[0],width,tileU);
                                const double a=alpha?std::max(0.0,std::min(1.0,double(alpha[index]))):1.0;
                                if(alpha) covered+=a*w[2];
                                for(int k=0;k<3;++k) found[k]+=double(pixels[index*3+k])*w[2]*a;
                            }
                            if(alpha) for(int k=0;k<3;++k) found[k]/=std::max(1e-12,covered);
                            for(int k=0;k<3;++k) foreground[k]+=found[k]*weight*covered;
                            coverage+=covered*weight;
                        }
                        if(kinds[l]==4) { if(total>0) for(int k=0;k<3;++k) foreground[k]/=total; }
                        else if(coverage>0) for(int k=0;k<3;++k) foreground[k]/=coverage;
                    } else {
                        const double* m=turns+l*9;
                        double d[3]={direction[0],direction[1],direction[2]};
                        bool turned=false;
                        for(int k=0;k<9;++k) if(m[k]!=0) {turned=true;break;}
                        if(turned) for(int i=0;i<3;++i) d[i]=direction[0]*m[0*3+i]+direction[1]*m[1*3+i]+direction[2]*m[2*3+i];
                        const double length=std::max(1e-12,std::sqrt(d[0]*d[0]+d[1]*d[1]+d[2]*d[2]));
                        const double u0=.5+std::atan2(d[0],d[2])/(2*PI);
                        const double v0=.5+std::asin(std::max(-1.0,std::min(1.0,d[1]/length)))/PI;
                        const double* t=uv+l*10;
                        const double tx=t[0]*u0+t[1]*v0+t[2],ty=t[3]*u0+t[4]*v0+t[5];
                        double u=(tx*t[6]-ty*t[7])*t[8],v=(tx*t[7]+ty*t[6])*t[9];
                        if(kinds[l]==4) {
                            // A procedural: its pattern at this point of its UVs, its alpha its coverage.
                            float rgb[3],grey[3];
                            modo_procedural_point(patterns[l],u,v,rgb,grey);
                            for(int k=0;k<3;++k) foreground[k]=rgb[k];
                            coverage=grey[0];
                        } else {
                        u=u*width-.5; v=v*height-.5;
                        const double fx=std::floor(u),fy=std::floor(v);
                        const double ax=u-fx,ay=v-fy;
                        const long long ix=(long long)fx,iy=(long long)fy;
                        const float* pixels=images[l];
                        const float* alpha=alphas[l];
                        coverage=alpha?0.0:1.0;
                        const double weights[4][3]={{0,0,(1-ax)*(1-ay)},{1,0,ax*(1-ay)},{0,1,(1-ax)*ay},{1,1,ax*ay}};
                        for(const auto& w:weights) {
                            const long long row=std::max(0LL,std::min((long long)height-1,iy+(long long)w[1]));
                            long long column=(ix+(long long)w[0])%width; if(column<0) column+=width;
                            const long long index=row*width+column;
                            const double a=alpha?std::max(0.0,std::min(1.0,double(alpha[index]))):1.0;
                            if(alpha) coverage+=a*w[2];
                            for(int k=0;k<3;++k) foreground[k]+=double(pixels[index*3+k])*w[2]*a;
                        }
                        if(alpha) for(int k=0;k<3;++k) foreground[k]/=std::max(1e-12,coverage);
                        }
                    }
                    if(inverts[l]) for(int k=0;k<3;++k) foreground[k]=1-foreground[k];
                    const double opacity=std::max(0.0,std::min(1.0,opacities[l]*coverage));
                    for(int k=0;k<3;++k) colour[k]=colour[k]+(component(modes[l],colour[k],foreground[k])-colour[k])*opacity;
                }
                float* to=out+((long long)y*width+x)*3;
                for(int k=0;k<3;++k) to[k]=float(colour[k]);
            }
        }
    };
    std::vector<std::thread> pool;
    const int step=(height+threads-1)/threads;
    for(int t=0;t<threads;++t) {
        const int begin=t*step,end=std::min(height,begin+step);
        if(begin>=end) break;
        pool.emplace_back(rows,begin,end);
    }
    for(auto& thread:pool) thread.join();
    return 0;
}

extern "C" __declspec(dllexport) int MR_environment_blend(int width,int height,int count,const int* kinds,const int* modes,
        const double* opacities,const int* inverts,const float* const* images,const float* const* alphas,const double* turns,
        const double* uv,const double* colours,const double* gradients,float* out,int threads) {
    for(int l=0;l<count;++l) if(kinds[l]<0||kinds[l]>2) return 1;
    return blend_layers(width,height,count,kinds,modes,opacities,inverts,images,alphas,turns,uv,colours,gradients,nullptr,nullptr,nullptr,out,threads);
}

// As MR_environment_blend, and two kinds more: 3 Modo's physical sky (skies[l]: daylight's numbers above, then its
// table, 16 x 24 x 3), 4 a procedural (patterns[l]: MR_procedural_bake's 31 settings), placed as an image is. The
// environment's layers with a physical sky or a procedural were laid in Python, pixel by pixel.
extern "C" __declspec(dllexport) int MR_environment_layers(int width,int height,int count,const int* kinds,const int* modes,
        const double* opacities,const int* inverts,const float* const* images,const float* const* alphas,const double* turns,
        const double* uv,const double* colours,const double* gradients,const double* const* skies,const double* const* patterns,
        float* out,int threads) {
    for(int l=0;l<count;++l) {
        if(kinds[l]<0||kinds[l]>4) return 1;
        if(kinds[l]==3&&(!skies||!skies[l])) return 1;
        if(kinds[l]==4&&(!patterns||!patterns[l])) return 1;
        if(kinds[l]==0&&!images[l]) return 1;
    }
    return blend_layers(width,height,count,kinds,modes,opacities,inverts,images,alphas,turns,uv,colours,gradients,skies,patterns,nullptr,out,threads);
}

// As MR_environment_layers, each image or procedural laid by one of Modo's Texture Locator projections where its
// projections numbers (PROJECTION_SIZE a layer, environment_projections.numbers) say so: kind 0 is the plain
// latitude-longitude layer above. MoonRay Source Override "Environment images in every projection"
// (native.environment_projections); an environment image laid otherwise than by a spherical projection was refused.
// Which of environment_projections' arithmetic MR_environment_projected lays (environment_layers.PROJECTIONS_VERSION):
// 2 Modo's own Grid and Dots in an environment (environment_procedural_point) and its Light Probe turn.
extern "C" __declspec(dllexport) int MR_environment_projections_version() { return 2; }

extern "C" __declspec(dllexport) int MR_environment_projected(int width,int height,int count,const int* kinds,const int* modes,
        const double* opacities,const int* inverts,const float* const* images,const float* const* alphas,const double* turns,
        const double* uv,const double* colours,const double* gradients,const double* const* skies,const double* const* patterns,
        const double* projections,float* out,int threads) {
    for(int l=0;l<count;++l) {
        if(kinds[l]<0||kinds[l]>4) return 1;
        if(kinds[l]==3&&(!skies||!skies[l])) return 1;
        if(kinds[l]==4&&(!patterns||!patterns[l])) return 1;
        if(kinds[l]==0&&!images[l]) return 1;
        const double kind=projections?projections[l*PROJECTION_SIZE]:0;
        if(kind<0||kind>8||(kind!=0&&kinds[l]!=0&&kinds[l]!=4)) return 1;
    }
    return blend_layers(width,height,count,kinds,modes,opacities,inverts,images,alphas,turns,uv,colours,gradients,skies,patterns,projections,out,threads);
}
