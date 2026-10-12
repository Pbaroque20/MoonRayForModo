"""Content-addressed package assets; hard links save space within a sequence."""
import os,shutil,uuid
from pathlib import Path

def copy(source,destination,store=None):
 from .assets import file_hash
 source=Path(source);destination=Path(destination)
 digest=file_hash(source)
 canonical=source
 if store is not None:
  store=Path(store).resolve();store.mkdir(parents=True,exist_ok=True)
  canonical=store/(digest+source.suffix.lower());canonical.resolve().relative_to(store)
  if canonical.exists():
   if file_hash(canonical)!=digest:raise ValueError('Shared package asset was modified: '+str(canonical))
  else:
   staged=store/(digest+'.'+uuid.uuid4().hex+'.partial')
   try:
    shutil.copy2(str(source),str(staged))
    if file_hash(staged)!=digest:raise ValueError('Source asset changed while packaging: '+str(source))
    staged.replace(canonical)
   finally:
    if staged.exists():staged.unlink()
 # Never copy over an existing hard link: that would modify other packages.
 staged=destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.partial')
 try:
  if store is None:shutil.copy2(str(source),str(staged))
  else:
   try:os.link(str(canonical),str(staged))
   except OSError:shutil.copy2(str(canonical),str(staged))
  if file_hash(staged)!=digest:raise ValueError('Source asset changed while packaging: '+str(source))
  staged.replace(destination)
 finally:
  if staged.exists():staged.unlink()
 return digest
