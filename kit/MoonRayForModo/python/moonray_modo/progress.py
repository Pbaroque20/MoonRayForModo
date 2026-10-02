"""Incremental MoonRay progress parsing; estimates cover the current render pass."""
import re,time

def duration(seconds):
    seconds=max(0,int(seconds));h,seconds=divmod(seconds,3600);m,s=divmod(seconds,60)
    return ('%dh %02dm %02ds'%(h,m,s)) if h else ('%dm %02ds'%(m,s))

class Progress:
    def __init__(self,clock=time.monotonic):
        self.clock=clock;self.started=clock();self.reset_pass()
    def reset_pass(self):
        self.tail='';self.percent=None;self.first=None;self.last=None
    def feed(self,text):
        self.tail+=text
        lines=re.split(r'[\r\n]',self.tail);self.tail=lines.pop()[-1024:]
        for line in lines:
            match=re.search(r'Rendering\s*\[\s*(\d+(?:\.\d+)?)%\]',line)
            if not match: continue
            value=min(100.,max(0.,float(match.group(1))));now=self.clock()
            if self.percent is None or value>self.percent:
                self.percent=value
                if self.first is None: self.first=(now,value)
                self.last=(now,value)
    def display(self,phase='render'):
        elapsed=self.clock()-self.started
        label='Elapsed '+duration(elapsed)
        if phase!='render': return -1,label+' · '+{'denoise':'Denoising','convert':'Updating display','postdone':'Saving output'}.get(phase,'Preparing')+' · Remaining: estimating'
        if self.percent is None: return -1,label+' · Preparing scene · Remaining: estimating'
        remaining=None
        if self.first and self.last:
            dt=self.last[0]-self.first[0];dp=self.last[1]-self.first[1]
            if dt>=2 and dp>=1 and self.percent<100:
                remaining=max(0.,dt/dp*(100-self.percent)-(self.clock()-self.last[0]))
        return int(self.percent),label+' · '+('Estimated pass remaining: ~'+duration(remaining) if remaining is not None and remaining>0 else 'Remaining: estimating')
