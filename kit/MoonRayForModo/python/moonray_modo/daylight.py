"""Single-scattering atmosphere approximation; not Modo's proprietary sky model.

Distances are metres. RGB Rayleigh coefficients approximate 680/550/440 nm;
Mie uses a Henyey-Greenstein phase function. Ozone and multiple scattering are
not modeled. The existing sun light supplies direct illumination (no baked disc).
"""
import math

GROUND = 6360000.0
TOP = GROUND + 100000.0
RAYLEIGH = (5.8e-6, 13.5e-6, 33.1e-6)


def exit_distance(position, direction, radius):
    b = sum(a*b for a,b in zip(position,direction))
    c = sum(a*a for a in position)-radius*radius
    discriminant = b*b-c
    return max(0,-b+math.sqrt(discriminant)) if discriminant>=0 else 0


def densities(position):
    altitude = max(0,math.sqrt(sum(v*v for v in position))-GROUND)
    return math.exp(-altitude/8000), math.exp(-altitude/1200)


def color(direction, environment):
    sun = environment['sun_direction']
    norm = math.sqrt(sum(v*v for v in sun))
    if norm<=0: raise ValueError('Invalid sun direction')
    sun = [v/norm for v in sun]
    if direction[1]<0:
        # Lambertian ground fill approximation, not a second environment light.
        return [max(0,sun[1])*.03*c for c in environment.get('ground_albedo',[.2]*3)]
    if sun[1]<-.1: return [0,0,0]
    origin = (0,GROUND+2,0)
    distance = exit_distance(origin,direction,TOP)
    step = distance/16
    optical_r = optical_m = 0
    integral_r = [0,0,0]; integral_m = [0,0,0]
    mie = 2e-5*max(.01,environment.get('haze',1))
    for i in range(16):
        position = [a+b*(i+.5)*step for a,b in zip(origin,direction)]
        r,m = densities(position)
        optical_r += r*step; optical_m += m*step
        light_step = exit_distance(position,sun,TOP)/8
        light_r = light_m = 0
        blocked = False
        for j in range(8):
            point = [a+b*(j+.5)*light_step for a,b in zip(position,sun)]
            if sum(v*v for v in point)<GROUND*GROUND:
                blocked = True; break
            lr,lm = densities(point)
            light_r += lr*light_step; light_m += lm*light_step
        if blocked: continue
        for channel,beta in enumerate(RAYLEIGH):
            attenuation = math.exp(-beta*(optical_r+light_r)-mie*(optical_m+light_m))
            integral_r[channel] += r*step*attenuation
            integral_m[channel] += m*step*attenuation
    mu = max(-1,min(1,sum(a*b for a,b in zip(direction,sun))))
    phase_r = 3*(1+mu*mu)/(16*math.pi)
    g = .76
    phase_m = (1-g*g)/(4*math.pi*(1+g*g-2*g*mu)**1.5)
    intensity = environment.get('solar_radiance',20)
    return [intensity*(beta*phase_r*integral_r[i]+mie*phase_m*integral_m[i]) for i,beta in enumerate(RAYLEIGH)]
