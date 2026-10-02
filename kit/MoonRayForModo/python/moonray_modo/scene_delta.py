"""Conservative deltas for our generated RDLA, never for arbitrary user Lua."""
import re

OBJECT = re.compile(r'(\w+\("(?:\\.|[^"\\])*"\)|SceneVariables)\s*\{\s*$')
ATTRIBUTE = re.compile(r'^\s*\[("(?:\\.|[^"\\])*")\]\s*=\s*(.*?)\s*,?\s*$')
STRINGS = re.compile(r'"(?:\\.|[^"\\])*"')
IDENTIFIERS = re.compile(r'\b[A-Za-z_][A-Za-z_0-9]*\b')
LITERALS = {'true','false','Rgb','Rgba','Vec2','Vec3','Vec4','Mat4','blur'}
# These affect layout/geometry representation; rebuild a clean scene context.
STRUCTURAL = {'"image_width"','"image_height"','"vertices_by_index"',
              '"face_vertex_count"','"part_list"','"part_face_count_list"',
              '"part_face_indices"','"is_subd"','"sub_viewport"'}


def difference(previous, current):
    """Return changed attribute blocks, or None when a full scene load is needed.

    Identical structure/line positions prove object declarations and connections
    have not changed. Only self-contained values may enter the delta; expressions
    referencing Lua locals, bindings, or different scene objects force a reload.
    """
    before,after=previous.splitlines(),current.splitlines()
    if len(before)!=len(after):return None
    owner=None
    changes={}
    for old,new in zip(before,after):
        opened=OBJECT.search(new)
        if opened:
            owner=opened.group(1)
        if old!=new:
            left,right=ATTRIBUTE.match(old),ATTRIBUTE.match(new)
            if owner is None or not left or not right or left.group(1)!=right.group(1):return None
            if right.group(1) in STRUCTURAL:return None
            value=right.group(2).rstrip(',').strip()
            # Strip quoted strings and numeric literals before checking constructors.
            for expression in (left.group(2),value):
                tokens=STRINGS.sub('',expression)
                tokens=re.sub(r'(?<![A-Za-z_])[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?','',tokens)
                if any(word not in LITERALS for word in IDENTIFIERS.findall(tokens)):return None
            changes.setdefault(owner,[]).append('  [%s] = %s,'%(right.group(1),value))
        if new.strip() in ('}', '})'):owner=None
    return '\n'.join(owner+' {\n'+'\n'.join(values)+'\n}' for owner,values in changes.items())+'\n'
