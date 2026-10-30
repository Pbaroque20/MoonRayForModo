"""Private Windows reference snapshot. Does not install, publish, or patch it."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024), b""):
            h.update(b)
    return h.hexdigest()


def inventory(root, workers=1):
    root=Path(root).resolve()
    if type(workers) is not int or not 1<=workers<=4:raise ValueError("Hash worker bound")
    files=[]
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            raise ValueError("Reference snapshot must not contain symlinks")
        if p.is_file():
            files.append(p)
    def entry(p):
        return p.relative_to(root).as_posix(),{"bytes":p.stat().st_size,"sha256":sha(p)}
    if workers==1:return dict(map(entry,files))
    # Every byte is still hashed against the pin; there is no timestamp shortcut.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=workers) as pool:return dict(pool.map(entry,files))


def identity(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,
        separators=(",",":"),allow_nan=False).encode()).hexdigest()


def verify(root, lock, workers=1):
    if lock["identity"] != identity(lock["contract"]):
        raise ValueError("Reference lock has changed")
    actual=inventory(root,workers)
    expected=lock["contract"]["files"]
    if actual!=expected:
        raise ValueError("Reference files changed: "+", ".join(
            k for k in sorted(actual.keys()|expected.keys())
            if actual.get(k)!=expected.get(k))[:500])


def snapshot(source, target, repo):
    source,target,repo=map(lambda p:Path(p).resolve(),(source,target,repo))
    if target.exists() or source==target or source in target.parents:
        raise ValueError("Use a fresh snapshot directory outside the source")
    required=("moonray.exe","rdl2_convert.exe","oiiotool.exe",
              "build-manifest.json","provenance/sources.json")
    if any(not (source/p).is_file() for p in required):
        raise ValueError("Missing reference tools or provenance")
    original=inventory(source)
    supplied=json.loads((source/"build-manifest.json").read_text())
    for name,item in supplied.items():
        if sha(source/name)!=item["sha256"]:
            raise ValueError("Release manifest mismatch: "+name)
    git=["git","-c","safe.directory="+repo.as_posix(),"-C",str(repo)]
    tag=subprocess.check_output(git+["rev-parse","v0.4.2^{commit}"]).decode().strip()
    tag_sources=json.loads(subprocess.check_output(
        git+["show","v0.4.2:patches/native-windows/sources.json"]))
    runtime_sources=json.loads((source/"provenance/sources.json").read_text())
    differences={}
    for name,item in runtime_sources["repositories"].items():
        if item!=tag_sources["repositories"].get(name):
            differences[name]={"bundled":item,"release_tag":tag_sources["repositories"].get(name)}
    markers={}
    for name in ("moonray.exe","librendering_rndr.dll","librendering_geom.dll"):
        blob=(source/name).read_bytes()
        markers[name]=any(s in blob for s in (b"XPU2_",b"XPU_PLUS_"))
    if any(markers.values()):
        raise ValueError("Candidate experiment switches found in reference binaries")
    shutil.copytree(source,target,copy_function=shutil.copy2)
    if inventory(target)!=original or inventory(source)!=original:
        raise ValueError("Snapshot or source changed during copying")
    contract={"schema":1,"baseline":"MoonRayForModo Windows port release-0.4.2",
        "release_tag_commit":tag,"files":original,"release_manifest_verified":len(supplied),
        "source_manifest_differences":differences,"experimental_switch_scan":markers,
        "provenance_status":"binary-pinned; source-to-binary rebuild not verified",
        "provenance_limit":"No marker strings is supporting evidence, not proof of absence. "
            "Bundled patch hashes differ from the release tag; no clean-rebuild claim.",
        "source_policy":"Windows port; no new XPU2 patches applied to this snapshot"}
    lock={"identity":identity(contract),"contract":contract}
    return lock


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source",required=True,type=Path)
    p.add_argument("--target",required=True,type=Path)
    p.add_argument("--repo",required=True,type=Path)
    p.add_argument("--lock",required=True,type=Path)
    a=p.parse_args()
    if a.lock.exists():
        raise ValueError("Refusing to replace an existing lock")
    lock=snapshot(a.source,a.target,a.repo)
    a.lock.write_text(json.dumps(lock,indent=2)+chr(10),encoding="utf-8")
    print("Pinned",len(lock["contract"]["files"]),"files",lock["identity"],flush=True)


if __name__=="__main__":
    main()
