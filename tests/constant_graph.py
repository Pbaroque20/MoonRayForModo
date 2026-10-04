"""Evaluate constant-only exported map expressions for independent numeric assertions.
Intentionally rejects textures and unsupported modes instead of approximating them.
"""
import math,re

def evaluate(lines,expression):
    blocks={}
    for match in re.finditer(r'ModoTextureMap\("([^"\n]+)"\) \{(.*?)\n\}', '\n'.join(lines),re.S):
        blocks[match[1]]={a:b for a,b in re.findall(r'\["([^"]+)"\] = (.*),',match[2])}
    def color(text):
        text=text.strip()
        if text.startswith('Rgb('):
            values=[float(v.strip()) for v in text[4:-1].split(',')]
            return values*3 if len(values)==1 else values
        match=re.fullmatch(r'bind\(ModoTextureMap\("([^"]+)"\)(?:, (.*))?\)',text)
        if match:
            attrs=blocks[match[1]];mode=int(attrs.get('mode','0'))
            a=color(attrs.get('background','Rgb(0)'));b=color(attrs.get('foreground','Rgb(1)'))
            if mode==11:result=[-math.log(max(1e-6,min(1,v)))*density for v,density in zip(b,a)]
            elif mode==0:
                blend=int(attrs.get('blend','0'));opacity=float(attrs.get('opacity','1'))
                if 'mask' in attrs:raise AssertionError('Mask evaluation is outside this fixture')
                if blend==0:mixed=b
                elif blend==1:mixed=[x*y for x,y in zip(a,b)]
                elif blend==3:mixed=[x-y for x,y in zip(a,b)]
                else:raise AssertionError('Unsupported constant blend '+str(blend))
                result=[x*(1-opacity)+y*opacity for x,y in zip(a,mixed)]
            else:raise AssertionError('Unsupported constant map mode '+str(mode))
            multiplier=color(match[2]) if match[2] else [1]*3
            return [x*y for x,y in zip(result,multiplier)]
        return [float(text)]*3
    return color(expression)
