"""Inspect and trim completed texture-cache entries without touching source assets."""
import os,tempfile,time
from pathlib import Path

def root():return (Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir()))/'MoonRayForModo/Textures').resolve()

def entries():
    folder=root()
    if not folder.exists():return []
    return [p for p in folder.rglob('*.tx') if p.is_file() and not p.is_symlink()]

def summary():
    files=entries();return len(files),sum(p.stat().st_size for p in files)

def trim(budget_mb,min_age_days=7):
    if budget_mb<0 or min_age_days<1:raise ValueError('Invalid cache retention settings')
    folder=root();files=entries();total=sum(p.stat().st_size for p in files);removed=0
    cutoff=time.time()-min_age_days*86400
    for file in sorted(files,key=lambda p:p.stat().st_mtime):
        if total<=budget_mb*1048576:break
        # Resolve every target within the owned cache, including any parent junctions.
        file.resolve().relative_to(folder)
        if file.stat().st_mtime>cutoff:continue
        try:size=file.stat().st_size;file.unlink();total-=size;removed+=1
        except OSError:continue  # A render or converter may still have the file open.
    return removed,total
