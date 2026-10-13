"""Smart Render: a MoonRay render is stopped once its picture is clean enough for the denoiser, and denoised.

How noisy the picture is, is read from the picture itself as it comes on: at pixels spread over it, how far each
stands from the line through its neighbours, across and up and down, the lesser of the two (so that an edge, which is
far out one way only, is not taken for noise), set against how bright it is there. The middle value of those is the
picture's noise: half of it is cleaner than that. A render samples a pixel again and again and that figure falls as
it does; when it has stood at or under the level asked for, for two looks running, the render is stopped as Stop
stops it, keeping the picture, and the denoiser does the rest.

Two things are kept out of that. As a pass begins MoonRay shows a coarse picture, each sample spread over a block of
pixels, and fills it in: pixels the same as their neighbours to the last digit are no sign of a clean picture, and
while many are, the picture is not judged. And where a pixel and all four of its neighbours are the same (a plain
background), there is nothing to read: such pixels are left out, so that a noisy subject on a plain background is
judged by the subject.

A picture full of fine texture reads as noisier than it is, and may never come down to a level: such a render simply
runs to its end, as it would without Smart Render.
"""
from array import array
import math

# The levels to choose from: the noise at which the render is stopped, as a share of a pixel's brightness. (On the
# coffee maker example scene, which reads 5.7% ten seconds into its long pass and 2.9% fifty seconds in, these stop
# the render 62, about 70 and 100 seconds into the 137 it takes.)
LEVELS = {'draft': 0.08, 'medium': 0.045, 'fine': 0.03}
CHOICES = [('Off', 'off'), ('Draft: stop soonest', 'draft'), ('Medium', 'medium'), ('Fine: stop latest', 'fine')]
# How many pixels are looked at, at most; how many of those must have something in them for the picture to be
# judged, as a share; how often it is looked at, in seconds; and how many looks running must be clean enough.
# (Black is not taken for a part not yet rendered: a subject on a black background is most of it black, and was
# never judged at all while it was. What is black is left out, and the rest is what is read.)
SAMPLES = 12000
LIT = 0.01
EVERY = 2.0
LOOKS = 2
# Set against a pixel's brightness, with this added so that what is nearly black does not count as all noise.
FLOOR = 0.05
# The picture is taken to be coarse still, and not judged, while more than this share of its pixels are the very
# same as a neighbour: a pass's first seconds, when most of it is. Not fewer: a render that is stopped finishes
# the tiles it has in hand before its picture is taken, so a few tiles still being filled in are no reason to
# go on, and held to a two-hundredth a render that read clean was never stopped at all.
COARSE = 0.05


last = {}


def noise(width, height, pixels):
    """(noise, share of the picture that is not black) of a picture given as float RGB, three numbers a pixel, row
    after row. noise is None where there is next to nothing in the picture yet, or it is still coarse: this is
    the reading a render is stopped by."""
    value, share, coarse = reading(width, height, pixels)
    return (None if coarse else value), share


def reading(width, height, pixels):
    """(noise, share of the picture that is not black, whether part of it is still coarse). The noise is read
    from the part of the picture that has been filled in, and is there to be shown whether or not the rest has:
    None only where next to nothing has been filled in yet."""
    width, height = int(width), int(height)
    if width < 8 or height < 8 or len(pixels) != width * height * 12:
        return None, 0.0, False
    values = array('f')
    values.frombytes(bytes(pixels) if not isinstance(pixels, (bytes, bytearray)) else pixels)
    step = max(2, int(math.sqrt(width * height / float(SAMPLES))))
    row = width * 3
    found = []
    looked = rendered = same = 0
    for y in range(1 + (step // 2) % 2, height - 1, step):
        base = y * row
        for x in range(1, width - 1, step):
            at = base + x * 3
            here = .2126 * values[at] + .7152 * values[at + 1] + .0722 * values[at + 2]
            looked += 1
            # Black: a background, or a part MoonRay has not reached. Nothing to read either way.
            if not here > 0.0:
                continue
            left = .2126 * values[at - 3] + .7152 * values[at - 2] + .0722 * values[at - 1]
            right = .2126 * values[at + 3] + .7152 * values[at + 4] + .0722 * values[at + 5]
            up = .2126 * values[at - row] + .7152 * values[at - row + 1] + .0722 * values[at - row + 2]
            down = .2126 * values[at + row] + .7152 * values[at + row + 1] + .0722 * values[at + row + 2]
            rendered += 1
            l, r, u, d = here == left, here == right, here == up, here == down
            if l and r and u and d:
                # A plain patch: nothing to read here.
                continue
            if l + r + u + d == 3:
                # The same on three sides: the edge of a plain patch. Of a block a sample was spread over, if
                # what lies on the fourth side is a block too (the same as what lies beyond it); else the
                # outline of something against a plain backdrop, which says nothing either way.
                if not l or not r:
                    step_to = -3 if not l else 3
                    inside = 2 <= x < width - 2
                else:
                    step_to = -row if not u else row
                    inside = 2 <= y < height - 2
                if not inside:
                    continue
                near, far = at + step_to, at + 2 * step_to
                if (.2126 * values[near] + .7152 * values[near + 1] + .0722 * values[near + 2]
                        != .2126 * values[far] + .7152 * values[far + 1] + .0722 * values[far + 2]):
                    continue
                same += 1
                continue
            elif l != r or u != d:
                # The same as the pixel on one side and not on the other: the edge or the corner of a block.
                # (The same on both sides is something that does not change that way, a backdrop's band.)
                # A block says nothing of the noise: it is counted, and not read.
                same += 1
                continue
            across = abs(2 * here - left - right)
            along = abs(2 * here - up - down)
            found.append(.5 * (across if across < along else along) / (here + FLOOR))
    if not looked:
        return None, 0.0, False
    share = rendered / float(looked)
    coarse = same > COARSE * (len(found) + same)
    # Kept for whoever wants to know why a picture was or was not judged.
    last.update(read=len(found), blocks=same, looked=looked)
    if len(found) < max(64, LIT * looked):
        return None, share, coarse
    found.sort()
    return found[len(found) // 2], share, coarse


class Watch:
    """Looks at a render's picture as it comes on and says when it is clean enough."""

    def __init__(self, level, clock):
        self.level = level if level in LEVELS else None
        self.threshold = LEVELS.get(level)
        self.clock = clock
        self.looked = None
        self.clean = 0
        self.noise = None
        # Whether part of the picture was still coarse at the last look: it is not stopped while it is.
        self.coarse = False
        self.settled = False

    def look(self, width, height, pixels):
        """Take a look if it is time for one. Returns True once, when the picture has become clean enough."""
        if self.threshold is None or self.settled:
            return False
        now = self.clock()
        if self.looked is not None and now - self.looked < EVERY:
            return False
        self.looked = now
        value, _, self.coarse = reading(width, height, pixels)
        # What it reads is kept to be shown, whether or not the picture is ready to be judged by it.
        self.noise = value
        if value is None or self.coarse:
            self.clean = 0
            return False
        self.clean = self.clean + 1 if value <= self.threshold else 0
        if self.clean >= LOOKS:
            self.settled = True
            return True
        return False
