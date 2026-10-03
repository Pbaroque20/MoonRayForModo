"""Explicitly install an untested development kit with rollback and an isolated runtime."""
import argparse
import csv
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''): value.update(block)
    return value.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unverified-development',action='store_true',required=True)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--geometry',type=Path,required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    runtime=args.runtime.resolve();geometry=args.geometry.resolve()
    if runtime== (root/'runtime/native-avx').resolve():
        raise ValueError('Use a separate candidate runtime; preserve the validated runtime')
    for name in ('moonray.exe','maketx.exe','oiiotool.exe','ModoTextureMap.so','DwaBaseMaterial.so','DwaLayerMaterial.so'):
        if not (runtime/name).is_file(): raise ValueError('Missing candidate runtime component: '+name)
    catalog=json.loads((root/'kit/MoonRayForModo/python/moonray_modo/material_catalog.json').read_text(encoding='utf-8'))
    for shader in catalog:
        if not (runtime/(shader+'.so')).is_file(): raise ValueError('Missing material shader: '+shader)
    maps=json.loads((root/'kit/MoonRayForModo/python/moonray_modo/map_catalog.json').read_text(encoding='utf-8'))
    for shader in maps:
        if not (runtime/(shader+'.so')).is_file():raise ValueError('Missing texture/normal shader: '+shader)
    build=json.loads(geometry.with_name('build.json').read_text(encoding='utf-8'))
    if not build.get('geometry_only') or digest(geometry)!=build.get('plugin_sha256'):
        raise ValueError('Geometry adapter does not match its build manifest')
    manifest=json.loads((runtime/'build-manifest.json').read_text(encoding='utf-8'))
    for name,entry in manifest.items():
        path=runtime/name
        if not path.is_file() or digest(path)!=entry['sha256']:
            raise ValueError('Staged runtime checksum mismatch: '+name)
    processes=subprocess.check_output(['tasklist','/FI','IMAGENAME eq modo.exe','/FO','CSV','/NH'],
        text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    if any(row and row[0].lower()=='modo.exe' for row in csv.reader(io.StringIO(processes))):
        raise ValueError('Close Modo before installing this development update; no processes were stopped')
    source=root/'kit/MoonRayForModo'
    destination=Path(os.environ['APPDATA'])/'Luxology/Kits/MoonRayForModo'
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup=root/'backups'/('before-development-'+stamp)
    staged=destination.with_name('MoonRayForModo-staging-'+stamp)
    previous=destination.with_name('MoonRayForModo-previous-'+stamp)
    kits=destination.parent.resolve()
    for path in (destination,staged,previous):
        path.resolve().relative_to(kits)
    backup.resolve().relative_to((root/'backups').resolve())
    if destination.exists(): shutil.copytree(destination,backup)
    shutil.copytree(source,staged,ignore=shutil.ignore_patterns('__pycache__','*.pyc','bin','runtime.json'))
    (staged/'bin').mkdir()
    shutil.copy2(geometry,staged/'bin/MoonRayGeometry.lx')
    (staged/'runtime.json').write_text(json.dumps({'directory':str(runtime),'installation_id':stamp},indent=2),encoding='utf-8')
    report={'status':'unverified development','tests_run':False,'runtime':str(runtime),
            'modo_executable':r'C:\Program Files\Modo16.1v9\modo\modo.exe',
            'backup':str(backup) if backup.exists() else None,
            'geometry_sha256':digest(geometry)}
    report['files']={path.relative_to(staged).as_posix():digest(path) for path in staged.rglob('*') if path.is_file()}
    (staged/'development-install.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    moved=False
    try:
        if destination.exists():
            destination.rename(previous);moved=True
        staged.rename(destination)
    except Exception:
        if moved and previous.exists() and not destination.exists(): previous.rename(destination)
        raise
    # Keep the previous checkout outside user:Kits so Modo cannot load two kits.
    if previous.exists():
        retained=root/'backups'/('previous-kit-'+stamp)
        retained.resolve().relative_to((root/'backups').resolve())
        previous.resolve().relative_to(kits)
        previous.rename(retained)
    (root/'test-results').mkdir(exist_ok=True)
    (root/'test-results/development-install.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'installed':str(destination),**report},indent=2))


if __name__=='__main__': main()
