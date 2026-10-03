"""Content-addressed package assets; hard links save space within a sequence."""
import os,shutil,uuid
from pathlib import Path

def copy(source,destination,store=None):
 from .assets import file_hash
 source=Path(source);destination=Path(destination)
 digest=file_hash(source)
 if store is None:shutil.copy2(str(source),str(destination));return digest
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
 try:os.link(str(canonical),str(destination))
 except OSError:shutil.copy2(str(canonical),str(destination))
 return digest
