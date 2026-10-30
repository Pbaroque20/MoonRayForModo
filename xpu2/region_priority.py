"""Region-priority blueprint for XPU2; not a native adaptive estimator.

Build immutable priorities from a completed sample checkpoint. Every active tile
remains in the ordering. Device costs are supplied measurements, not benchmarks
or proof that a GPU can execute an arbitrary material/path.
"""
from dataclasses import dataclass
import math
from xpu2.scheduling import uint


def nonnegative(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('Invalid ' + name)
    try:
        value = float(value)
    except OverflowError:
        raise ValueError('Invalid ' + name) from None
    if not math.isfinite(value) or value < 0:
        raise ValueError('Invalid ' + name)
    return value


@dataclass(frozen=True)
class Attention:
    # Normalized priorities, NOT the renderer's convergence/error threshold.
    noise: float = 0.0
    contrast: float = 0.0
    changed: bool = False
    waiting_epochs: int = 0

    def __post_init__(self):
        nonnegative(self.noise, 'noise priority')
        nonnegative(self.contrast, 'contrast priority')
        if type(self.changed) is not bool:
            raise ValueError('Invalid changed flag')
        uint(self.waiting_epochs, 'waiting epochs')
        if self.waiting_epochs > 2**32:
            raise ValueError('Waiting epoch counter overflow')

    @property
    def priority(self):
        # Aging can outrank visual importance, preventing permanent postponement.
        return (4 * min(self.noise, 1.0) + min(self.contrast, 1.0)
                + 2 * self.changed + self.waiting_epochs)


@dataclass(frozen=True)
class Region:
    x: int
    y: int
    size: int  # Square extent in tiles, including clipped/padded outer edges.
    priority: float
    children: tuple

    def ordered_tiles(self):
        if not self.children:
            return ((self.x, self.y),)
        return tuple(tile for child in self.children for tile in child.ordered_tiles())


class RegionHierarchy:
    """Sparse quadtree; prioritize subregions while preserving Morton tie order."""
    def __init__(self, width, height, tile_size=8, *, attention=None, active_tiles=None):
        for name, value in (('width', width), ('height', height), ('tile size', tile_size)):
            uint(value, name, True)
        wide, high = (width + tile_size - 1)//tile_size, (height + tile_size - 1)//tile_size
        def valid(tile):
            if not isinstance(tile, tuple) or len(tile) != 2:
                raise ValueError('Expected tile coordinates')
            x, y = tile
            uint(x, 'tile x'); uint(y, 'tile y')
            if x >= wide or y >= high:
                raise ValueError('Tile outside image')
        weights = dict(attention or {})
        for tile, value in weights.items():
            valid(tile)
            if not isinstance(value, Attention):
                raise ValueError('Expected immutable attention signals')
        active = (frozenset((x,y) for y in range(high) for x in range(wide))
                  if active_tiles is None else frozenset(active_tiles))
        for tile in active:
            valid(tile)
        def build(x, y, size, tiles):
            if size == 1:
                return Region(x, y, size, weights.get((x,y), Attention()).priority, ())
            half = size//2
            groups = [[], [], [], []]
            for tx, ty in tiles:
                groups[int(tx >= x+half) + 2*int(ty >= y+half)].append((tx,ty))
            children = [build(x+(q%2)*half, y+(q//2)*half, half, group)
                        for q, group in enumerate(groups) if group]
            children.sort(key=lambda child: -child.priority)  # Stable Morton tie order.
            return Region(x, y, size, max(c.priority for c in children), tuple(children))
        extent = 1 << (max(wide, high)-1).bit_length()
        self.root = build(0, 0, extent, active) if active else None
        self.order = self.root.ordered_tiles() if self.root else ()


@dataclass(frozen=True)
class DeviceCost:
    name: str
    capabilities: frozenset
    seconds_per_work: float
    queued_seconds: float = 0.0
    launch_seconds: float = 0.0
    transfer_seconds: float = 0.0

    def __post_init__(self):
        if self.name not in ('cpu', 'gpu'):
            raise ValueError('Unknown device')
        if not isinstance(self.capabilities, frozenset) or any(not isinstance(c, str) or not c for c in self.capabilities):
            raise ValueError('Expected immutable capability names')
        for name in ('seconds_per_work', 'queued_seconds', 'launch_seconds', 'transfer_seconds'):
            nonnegative(getattr(self, name), name)

    def completion_seconds(self, work):
        return nonnegative(self.queued_seconds + self.launch_seconds + self.transfer_seconds
                           + self.seconds_per_work*work, 'estimated completion')


def choose_device(work, required, devices, *, resources_ready=True):
    """Recommend an eligible device; None means defer, never fabricate a sample.

    This is a cost-policy model. The native dispatcher must enforce capabilities,
    retain resources and lease ownership, and update queue estimates after claims.
    """
    work = nonnegative(work, 'work estimate')
    if not isinstance(required, frozenset) or any(not isinstance(c,str) or not c for c in required):
        raise ValueError('Expected immutable required capabilities')
    devices = tuple(devices)
    if any(not isinstance(d, DeviceCost) for d in devices) or len({d.name for d in devices}) != len(devices):
        raise ValueError('Invalid/duplicate device estimates')
    if type(resources_ready) is not bool:
        raise ValueError('Invalid resource readiness')
    eligible = [d for d in devices if required <= d.capabilities] if resources_ready else []
    return min(eligible, key=lambda d: (d.completion_seconds(work), d.name)).name if eligible else None
