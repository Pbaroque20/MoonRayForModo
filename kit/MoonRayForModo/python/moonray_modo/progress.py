"""Incremental MoonRay progress parsing, and an estimate of the time left in the whole render.

A preview is rendered in passes: a quick one, a second, and the long one, each of more samples than the last. What
MoonRay reports is how far the pass now going has come. The estimate is of the render as a whole: the pass now going,
and the passes still to come, whose cost is known from how many samples each takes and how long a sample has been
taking. A render of one pass (an output) is that pass alone.

An adaptive render is another matter. What MoonRay reports of one is how many of its tiles have finished, and a
tile finishes when its noise is low enough. Where most of the picture needs all the samples it may have, that
climbs evenly and a time can be told from it. Where most of it settles early, nearly every tile finishes near the
end: on a render of five minutes the figure stood under 5% for four of them and ended at 36%, standing still for
half a minute at a time and going down as well as up. So a time is told of an adaptive render only while its
figure climbs steadily, and once it has stood still or gone back it is shown as what it is, for the rest of
that render.
"""
import re,time

# How much of the recent past is looked at beside the pass as a whole. A render speeds up and slows down as it moves
# between easy and hard parts of the picture; the recent rate says where it is now, and the pass's own rate keeps the
# figure from swinging with every easy or hard patch.
WINDOW=20.0
# How far a pass must have come, in percent of itself, before its own rate is taken at its word. Before that the rate
# learnt from the passes already done stands in for it: a pass's first seconds are spent starting, not rendering.
TRUSTED=20.0
# An adaptive render's figure is not gone by if it stands still this long while MoonRay goes on reporting, nor
# before it has reached this much, in percent, and climbed for this long.
STALLED=8.0;STEADY_FROM=2.0;STEADY_FOR=15.0
# The pause between one pass and the next, until one has been seen.
BETWEEN=3.0

def duration(seconds):
    seconds=max(0,int(seconds));h,seconds=divmod(seconds,3600);m,s=divmod(seconds,60)
    return ('%dh %02dm %02ds'%(h,m,s)) if h else ('%dm %02ds'%(m,s))

class Progress:
    def __init__(self,clock=time.monotonic):
        self.clock=clock;self.started=clock();self.generation=None
        # The work of each pass, in samples a pixel; None for a render of one pass or of passes unknown.
        self.units=None;self.index=0;self.adaptive=False;self.shaky=False;self.exact=False
        # What each pass done took, as (its work, its seconds); the pause between passes; when the last one ended.
        self.done=[];self.between=BETWEEN;self.ended=None
        # When the render is expected to end, by the clock: what is shown is how long until then.
        self.finish=None;self.percent=None
        self.reset_pass()
    def plan(self,units,adaptive=False):
        """Say what passes the render is made of, by the work in each (its samples a pixel), and whether it
        samples adaptively."""
        self.adaptive=bool(adaptive)
        units=[float(u) for u in (units or []) if u and float(u)>0]
        self.units=units if len(units)>1 else None;self.index=0
    def reset_pass(self):
        """A pass begins. If the one before it got anywhere, what it taught is kept and the count moves on."""
        if self.percent is not None and self.first and self.last:
            spent=self.last[0]-self.first[0];gained=self.last[1]-self.first[1]
            if self.units and self.index<len(self.units):
                if spent>0 and gained>5:self.done.append((self.units[self.index],spent/(gained/100.0)))
                self.index=min(self.index+1,len(self.units)-1)
            self.ended=self.last[0]
        self.tail='';self.percent=None;self.first=None;self.last=None;self.history=[];self.began=self.clock()
        if not self.units:self.finish=None
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
                self.exact=True
            else:
                match=re.search(r'Rendering\s*\[\s*(\d+(?:\.\d+)?)%\]',line)
                if not match: continue
                # MoonRay's own line gives the same figure in whole percents, a little behind: with the exact one
                # to hand it adds nothing, and looks like a step back.
                if self.exact:continue
                value=float(match.group(1))
            if value!=value:continue
            value=min(100.,max(0.,value));now=self.clock()
            if self.adaptive and self.percent is not None and self.percent<100 and (value<self.percent-.05 or (value<=self.percent and now-self.last[0]>STALLED)):
                self.shaky=True
            if self.percent is None or value>self.percent:
                if self.percent is None and self.ended is not None:
                    # How long it was between the last pass ending and this one getting under way.
                    self.between=.5*self.between+.5*max(0.0,min(30.0,now-self.ended))
                self.percent=value
                # A pass's first seconds are spent starting (the graphics card among them): its rate is counted
                # from where it got under way, not from its first sign of life.
                if self.first is None or (self.first[1]<1.0<=value and now-self.first[0]<60):self.first=(now,value)
                self.last=(now,value)
                self.history.append((now,value))
                while len(self.history)>2 and now-self.history[1][0]>=WINDOW:self.history.pop(0)
    def _pass_time(self,units):
        """How long a pass of this much work is expected to take, from the passes done, or None with none done.
        A pass costs something to begin whatever its size, and then so much a sample: with two passes done both are
        known; with one, the beginning is taken to be as long as the pause between passes."""
        if not self.done:return None
        work,spent=self.done[-1]
        start=min(self.between,.5*spent)
        if len(self.done)>1 and self.done[-2][0]!=work:
            before,earlier=self.done[-2]
            each=(spent-earlier)/(work-before)
            if each>0:start=max(0.0,min(spent-each*work,.8*spent))
        each=(spent-start)/work
        return start+each*units

    def _rate(self):
        """Percent of this pass a second, or None while there is nothing to go on. The pass's own rate since its first
        report, with a little of the recent rate; early in a pass, mostly what earlier passes say a sample costs."""
        expected=None
        if self.units and self.done:expected=100.0/self._pass_time(self.units[self.index])
        if not self.first or not self.last:return expected
        elapsed=self.last[0]-self.first[0];gained=self.last[1]-self.first[1]
        if elapsed<2.0 or gained<=0:return expected
        overall=gained/elapsed
        recent_elapsed=self.last[0]-self.history[0][0];recent_gained=self.last[1]-self.history[0][1]
        recent=recent_gained/recent_elapsed if recent_elapsed>=5.0 and recent_gained>0 else overall
        measured=.65*overall+.35*recent
        if expected is None:
            # Nothing earlier to go by: the pass's first few percent are too few to say anything of the rest.
            return measured if gained>=2.0 and elapsed>=4.0 else None
        weight=min(1.0,gained/TRUSTED)
        return weight*measured+(1-weight)*expected
    def remaining(self):
        """Seconds left in the render, or None while there is too little to go on."""
        now=self.clock();rate=self._rate()
        if self.adaptive and (self.shaky or self.percent is None or self.percent<STEADY_FROM or not self.first or now-self.first[0]<STEADY_FOR
                              or now-self.last[0]>STALLED):
            return None
        if self.percent is not None and self.percent>=100 and not (self.units and self.index<len(self.units)-1):return None
        if rate is None or rate<=0:return None
        if self.percent is None:
            # Between passes, or before this one's first report: the whole of it is still to do.
            left=100.0/rate+max(0.0,self.between-(now-(self.ended if self.ended is not None else self.began)))
        else:
            left=max(0.0,(100-self.percent)/rate-(now-self.last[0]))
        if self.units:
            # The passes to come, as the passes done say they will go; and if this one is going slower or faster
            # than they said it would, the ones after it are taken to as well.
            this=100.0/rate
            foretold=self._pass_time(self.units[self.index])
            for later in self.units[self.index+1:]:
                left+=self.between+(self._pass_time(later)*this/foretold if foretold else this*later/self.units[self.index])
        # The figure shown counts down by the clock, and is drawn towards each new estimate rather than jumping to it:
        # quickly when it is far out, gently when it is near.
        target=now+left
        if self.finish is None:self.finish=target
        else:
            off=target-self.finish
            self.finish+=(.35 if abs(off)>.3*max(left,5.0) else .12)*off
        return max(0.0,self.finish-now)
    def whole(self):
        """How far the whole render has come, in percent, or None before anything is known."""
        if not self.units:return self.percent
        done=sum(self.units[:self.index])+(self.percent or 0.0)/100.0*self.units[self.index]
        if self.percent is None and not self.index:return None
        return 100.0*done/sum(self.units)
    def display(self,phase='render'):
        elapsed=self.clock()-self.started
        label='Elapsed '+duration(elapsed)
        if phase!='render': return -1,label+' · '+{'denoise':'Denoising','convert':'Updating display','postdone':'Saving output'}.get(phase,'Preparing')
        percent=self.whole()
        if percent is None: return -1,label+' · Preparing scene'
        remaining=self.remaining()
        if self.adaptive and remaining is None:return int(percent),label+' · Adaptive sampling: %d%% of tiles finished'%percent
        return int(percent),label+' · '+('About '+duration(remaining)+' left' if remaining is not None and remaining>=1 else '%d%%'%percent)
