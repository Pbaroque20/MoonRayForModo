"""Single-owner control plane for XPU2 experiments, independent of Modo and CUDA.

Workers receive immutable revision tokens. All mutations and result publication
must be serialized by the coordinator; this object is not itself a thread lock.
No current scene is eligible for XPU2: no shading capability has been validated.
"""
from dataclasses import dataclass
from enum import Enum
import uuid


class Change(Enum):
    TOPOLOGY = "topology"
    POSITIONS = "positions"
    TRANSFORM = "transform"
    SHADING = "shading"
    VISIBILITY = "visibility"


@dataclass(frozen=True)
class ObjectRevision:
    identity: str
    revision: int
    dependencies: frozenset
    changes: frozenset


@dataclass(frozen=True)
class SceneDelta:
    base: int
    revision: int
    changed: tuple
    removed: tuple


class SceneIndex:
    """Versioned object metadata, not geometry storage.

    The caller supplies a complete dependency list for each edited object.
    Dependency changes conservatively rebuild dependents until attribute-specific
    dependency rules are validated. Missing dependencies are rejected.
    """
    def __init__(self):
        self.revision = 0
        self.objects = {}

    def apply(self, edits, removed=()):
        # edits: identity -> (Change collection, dependency identities).
        removed = frozenset(removed)
        if removed & edits.keys():
            raise ValueError("Cannot edit and remove the same object")
        if removed - self.objects.keys():
            raise ValueError("Cannot remove an unknown object")
        staged = dict(self.objects)
        next_revision = self.revision + 1
        for identity in removed:
            del staged[identity]
        changed = set(edits)
        for identity, (flags, dependencies) in edits.items():
            flags, dependencies = frozenset(flags), frozenset(dependencies)
            if not isinstance(identity, str) or not identity or not flags:
                raise ValueError("An edit requires an identity and change classification")
            if any(not isinstance(flag, Change) for flag in flags):
                raise ValueError("Unknown change classification")
            previous = self.objects.get(identity)
            # Creation and a changed dependency binding cannot be classified as
            # transform-only, even if the host supplied only that notice.
            if previous is None or previous.dependencies != dependencies:
                flags = frozenset(Change)
            staged[identity] = ObjectRevision(identity, next_revision, dependencies, flags)
        for entry in staged.values():
            if entry.dependencies - staged.keys():
                raise ValueError("Missing dependency for " + entry.identity)
        # Fixed point also handles cycles without recursion. A dependency cycle
        # is not evaluated here; every member is invalidated together.
        while True:
            affected = {key for key, value in staged.items()
                        if key not in changed and value.dependencies & changed}
            if not affected:
                break
            changed.update(affected)
            for identity in affected:
                entry = staged[identity]
                staged[identity] = ObjectRevision(
                    identity, next_revision, entry.dependencies, frozenset(Change))
        if not changed and not removed:
            return SceneDelta(self.revision, self.revision, (), ())
        delta = SceneDelta(self.revision, next_revision,
                           tuple(staged[key] for key in sorted(changed)),
                           tuple(sorted(removed)))
        # Publish atomically only after validation, preserving unchanged entries.
        self.objects, self.revision = staged, next_revision
        return delta


@dataclass(frozen=True)
class Attempt:
    revision: int
    engine: str
    identity: str


class RenderGate:
    """Reject stale/duplicate work and prevent mixed fallback accumulations.

    A reference identity is the content hash of a pinned runtime + scene lock.
    A new attempt always starts an empty set of completed sample batches.
    Pixel buffers must be owned by this attempt in the future native adapter.
    """
    def __init__(self, reference_identity):
        if not reference_identity:
            raise ValueError("A pinned reference is required")
        self.reference_identity = reference_identity
        self.active = None
        self.completed = set()
        self.fallback_reason = None

    def start(self, revision):
        if type(revision) is not int or revision < 0:
            raise ValueError("Invalid scene revision")
        self.active = Attempt(revision, "xpu", uuid.uuid4().hex)
        self.completed.clear()
        self.fallback_reason = "XPU2 has no validated shading capabilities yet"
        return self.active

    def restart_reference(self, reason):
        if self.active is None or not reason:
            raise ValueError("A running attempt and fallback reason are required")
        revision = self.active.revision
        self.active = Attempt(revision, "xpu", uuid.uuid4().hex)
        self.completed.clear()
        self.fallback_reason = str(reason)
        return self.active

    def accept(self, attempt, batch_id):
        if self.active is None or attempt != self.active:
            return False
        if not isinstance(batch_id, str) or not batch_id:
            raise ValueError("A stable sample-batch identity is required")
        if batch_id in self.completed:
            return False
        self.completed.add(batch_id)
        return True

    def cancel(self):
        self.active = None
        self.completed.clear()


@dataclass(frozen=True)
class Resource:
    """Revision-specific geometry or texture page, including its exact mip."""
    kind: str
    identity: str
    revision: int
    page: str = ""

    def __post_init__(self):
        if self.kind not in ("geometry", "texture"):
            raise ValueError("Unknown resource kind")
        if not self.identity or type(self.revision) is not int or self.revision < 0:
            raise ValueError("Invalid resource identity/revision")


class DemandQueue:
    """Deduplicate demands and release paths only when ALL resources are resident.

    This is a CPU model for protocol tests, not a GPU pager. No proxy intersection
    is treated as an actual surface hit. Requests have no bounce cutoff: prefetch
    policy must never suppress resources required by a real path.
    """
    def __init__(self, attempt):
        self.attempt = attempt
        self.resident = set()
        self.requested = set()
        self.pending = set()
        self.waiting = {}

    def defer(self, attempt, path_id, resources):
        if attempt != self.attempt:
            return False
        if path_id in self.waiting:
            raise ValueError("Path is already deferred")
        missing = frozenset(resources) - self.resident
        if not missing:
            return False
        self.waiting[path_id] = set(missing)
        self.pending.update(missing - self.requested)
        return True

    def requests(self):
        batch = tuple(sorted(self.pending,
                             key=lambda r: (r.kind, r.identity, r.revision, r.page)))
        self.requested.update(batch)
        self.pending.clear()
        return batch

    def available(self, attempt, resource):
        if attempt != self.attempt or resource not in self.requested:
            return ()
        self.resident.add(resource)
        ready = []
        for identity, missing in list(self.waiting.items()):
            missing.discard(resource)
            if not missing:
                ready.append(identity)
                del self.waiting[identity]
        return tuple(ready)

    def evict(self, resource):
        # Real device use must be fenced before calling this.
        self.resident.discard(resource)
        self.requested.discard(resource)

    def reset(self, attempt):
        self.__init__(attempt)
