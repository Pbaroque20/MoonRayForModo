"""Incremental MoonRay progress parsing; estimates cover the current render pass."""
import re,time

# How much of the recent past the rate of progress is measured over. A render speeds up and
# slows down as it moves between easy and hard parts of the picture, and adaptive sampling
# finishes the easy parts first, so the recent rate says more than the average since the start.
WINDOW=12.0

def duration(seconds):
    seconds=max(0,int(seconds));h,seconds=divmod(seconds,3600);m,s=divmod(seconds,60)
    return ('%dh %02dm %02ds'%(h,m,s)) if h else ('%dm %02ds'%(m,s))

class Progress:
    def __init__(self,clock=time.monotonic):
        self.clock=clock;self.started=clock();self.generation=None;self.reset_pass()
    def reset_pass(self):
        self.tail='';self.percent=None;self.first=None;self.last=None;self.history=[];self.estimate=None
    def feed(self,text):
        self.tail+=text
        lines=re.split(r'[\r\n]',self.tail);self.tail=lines.pop()[-1024:]
        for line in lines:
            # A persistent preview says how far it is itself; a batch render prints MoonRay's own line.
            match=re.match(r'@@MODO_PROGRESS (\S+) ([0-9.eE+-]+)\s*$',line)
            if match:
                if self.generation is not None and match.group(1)!=str(self.generation):continue
                try:value=float(match.group(2))*100.
                except ValueError:continue
            else:
                match=re.search(r'Rendering\s*\[\s*(\d+(?:\.\d+)?)%\]',line)
                if not match: continue
                value=float(match.group(1))
            if value!=value:continue
            value=min(100.,max(0.,value));now=self.clock()
            if self.percent is None or value>self.percent:
                self.percent=value
                if self.first is None: self.first=(now,value)
                self.last=(now,value)
                self.history.append((now,value))
                while len(self.history)>2 and now-self.history[1][0]>=WINDOW:self.history.pop(0)
    def remaining(self):
        """Seconds left in the pass, or None while there is too little to go on."""
        if not self.first or not self.last or self.percent is None or self.percent>=100:return None
        elapsed=self.last[0]-self.first[0];gained=self.last[1]-self.first[1]
        if elapsed<1.5 or gained<=0:return None
        overall=gained/elapsed
        recent_elapsed=self.last[0]-self.history[0][0];recent_gained=self.last[1]-self.history[0][1]
        recent=recent_gained/recent_elapsed if recent_elapsed>=1.5 and recent_gained>0 else overall
        # Mostly the recent rate, steadied by the average.
        rate=.7*recent+.3*overall
        left=max(0.,(100-self.percent)/rate-(self.clock()-self.last[0]))
        # The figure shown moves towards each new estimate rather than jumping with it.
        self.estimate=left if self.estimate is None else self.estimate+.35*(left-self.estimate)
        return self.estimate
    def display(self,phase='render'):
        elapsed=self.clock()-self.started
        label='Elapsed '+duration(elapsed)
        if phase!='render': return -1,label+' · '+{'denoise':'Denoising','convert':'Updating display','postdone':'Saving output'}.get(phase,'Preparing')
        if self.percent is None: return -1,label+' · Preparing scene'
        remaining=self.remaining()
        return int(self.percent),label+' · '+('About '+duration(remaining)+' left' if remaining is not None and remaining>=1 else '%d%%'%self.percent)
