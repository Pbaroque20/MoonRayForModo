"""Deferred regression checks; run explicitly, outside Modo."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo.channel_values import rgb,fresnel_controls


def main():
    assert rgb((.1,.2,.3),'albedo')==[.1,.2,.3]
    assert rgb([.3,.2,.1],'albedo')==[.3,.2,.1]
    assert rgb(.2,'albedo')==[.2,.2,.2]
    for value in ((1,2),(1,2,float('nan')),('bad',2,3)):
        try: rgb(value,'albedo')
        except ValueError: pass
        else: raise AssertionError('Malformed albedo accepted')
    assert fresnel_controls({},.04,0,1,0)==[]
    assert fresnel_controls({},0,0,0,0)==[]
    assert fresnel_controls({},.04,0,.5,0)==['Specular Fresnel']
    assert fresnel_controls({},0,.5,1,0)==['Reflection Fresnel']
    assert fresnel_controls({'native_shader':'DwaMetalMaterial'},1,1,0,0)==[]
    print('Channel conversion and Fresnel-warning regressions passed')

if __name__=='__main__': main()
