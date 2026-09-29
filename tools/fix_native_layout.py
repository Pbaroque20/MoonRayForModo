"""Apply narrow Windows layout/allocation fixes to the pinned upstream sources."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1] / 'upstream/openmoonray/moonray/scene_rdl2'
path = root / 'lib/scene/rdl2/rdl2_ispc_util/rdl2_ispc_util.cc'
path.write_text(path.read_text(encoding='utf-8').replace('%lu', '%zu'), encoding='utf-8')
path = root / 'tests/lib/common/fb_util/TestSnapshotUtil.cc'
text = re.sub(r'(?m)^(    )free\(', r'\1util::alignedFree(', path.read_text(encoding='utf-8'))
path.write_text(text, encoding='utf-8')
for name in ('Macros.h', 'ISPCSupport.h'):
    path = root / 'lib/scene/rdl2' / name
    text = re.sub(r'\bDECLARE_HANDLE\b', 'RDL2_DECLARE_HANDLE', path.read_text(encoding='utf-8'))
    path.write_text(text, encoding='utf-8')
