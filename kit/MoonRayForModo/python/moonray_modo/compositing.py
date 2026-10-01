"""Scoped channel compositing for pass-through texture groups.

The blend callback can produce either map references or numeric fixture values.
Whole-material groups and non-normal group blends are handled separately.
"""
import math


class Groups:
    def __init__(self, defaults, blend):
        self.current = dict(defaults)
        self.used = set()
        self.stack = []
        self.blend = blend
        self.mask_default = defaults['groupMask']

    def select(self, path):
        common = 0
        while common < min(len(path), len(self.stack)):
            if path[common] != self.stack[common][0]:
                break
            common += 1
        while len(self.stack) > common:
            self._close()
        for group in path[common:]:
            opacity = float(group.get('opacity', 1))
            if not math.isfinite(opacity) or not 0 <= opacity <= 1:
                raise ValueError('Texture group opacity must be between zero and one')
            if group.get('blend', 'normal') != 'normal':
                raise ValueError('Non-normal texture group blending is not translated')
            self.stack.append((dict(group), dict(self.current), self.used))
            self.used = set()
            self.current['groupMask'] = self.mask_default

    def _close(self):
        group, previous, parent_used = self.stack.pop()
        mask = self.current['groupMask'] if 'groupMask' in self.used else None
        affected = self.used - {'groupMask'}
        for effect in affected:
            self.current[effect] = self.blend(previous[effect], self.current[effect],
                                               group.get('opacity', 1), mask)
        self.current['groupMask'] = previous['groupMask']
        self.used = parent_used | affected

    def finish(self):
        self.select([])
        return self.current, self.used
