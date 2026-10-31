"""Make a Modo package (.lpk) of a release: the kit and its Windows runtime in one file, which Modo installs into
the user's Kits folder when it is dropped onto a viewport, in place of unpacking two ZIPs and copying folders by hand.

package_lpk.py <version> [--with-content]

Reads dist/release-<version>/MoonRayForModo-<version>-kit.zip and -windows-runtime.zip (made by
tools/package_development_release.py) and writes dist/release-<version>/MoonRayForModo-<version>.lpk. An .lpk is a ZIP
whose index.xml names the kit and lists each file with where it goes, relative to the Kits folder: so each target starts
with the kit's folder (without it Modo unpacks into Kits itself, as other kits' packages show). --with-content adds the
example scenes of the content ZIP to the asset library as well (about 300 MB more).

It replaces an older install: Modo only adds and overwrites, so the package names what earlier releases installed and
this one does not (superseded.txt, from dist/release-*'s kit and runtime ZIPs), and the kit, the first time it starts
after, moves those files aside (stale_files.py). Nothing else in the kit's folder is touched. The cleanup itself is taken
from this checkout, so a package made for a release already out has the current one. On install Modo shows the package's
message of thanks, and asks to restart itself (restart="YES").
"""
import argparse
import hashlib
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('version')
parser.add_argument('--with-content', action='store_true')
args = parser.parse_args()
folder = root / 'dist' / ('release-' + args.version)
sources = [folder / ('MoonRayForModo-%s-kit.zip' % args.version), folder / ('MoonRayForModo-%s-windows-runtime.zip' % args.version)]
if args.with_content:
    sources.append(folder / ('MoonRayForModo-%s-content.zip' % args.version))
missing = [str(p) for p in sources if not p.is_file()]
if missing:
    raise SystemExit('Package the release first; missing: ' + ', '.join(missing))

PREFIX = 'MoonRayForModo/'
target = folder / ('MoonRayForModo-%s.lpk' % args.version)
staged = target.with_suffix('.lpk.tmp')
CLEANUP = 'python/moonray_modo/stale_files.py'
cleanup = (root / 'kit/MoonRayForModo' / CLEANUP).read_bytes()
listed = []
seen = set()
with zipfile.ZipFile(staged, 'w', zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as package:
    for source in sources:
        with zipfile.ZipFile(source) as archive:
            for info in archive.infolist():
                if info.is_dir() or not info.filename.startswith(PREFIX):
                    continue
                inside = info.filename[len(PREFIX):]
                if inside in seen:
                    raise SystemExit('Two packages hold %s' % inside)
                seen.add(inside)
                # Stored under its own path in the package, and installed to the same place inside the kit.
                with archive.open(info) as data:
                    package.writestr(zipfile.ZipInfo(inside, info.date_time), cleanup if inside == CLEANUP else data.read(), zipfile.ZIP_DEFLATED)
                listed.append(inside)
    if 'index.cfg' not in seen:
        raise SystemExit('The kit ZIP has no index.cfg')
    # The list of what this version installs, which the kit reads to move aside what an older one left (stale_files.py).
    package.writestr('installed.txt', '%s\n%s\n' % (args.version, '\n'.join(sorted(listed + ['installed.txt']))))
    listed.append('installed.txt')
    # What earlier releases installed and this one does not: all that the kit moves aside.
    earlier = set()
    for release in sorted((root / 'dist').glob('release-*')):
        if release == folder or not release.is_dir():
            continue
        for held in list(release.glob('MoonRayForModo-*-kit.zip')) + list(release.glob('MoonRayForModo-*-windows-runtime.zip')):
            with zipfile.ZipFile(held) as archive:
                earlier.update(n[len(PREFIX):] for n in archive.namelist() if n.startswith(PREFIX) and not n.endswith('/'))
    KEPT = {'runtime.json', 'layout.cfg', 'development-install.json', 'moonray_keys.cfg'}
    superseded = sorted(n for n in earlier - set(listed) if n.rsplit('/', 1)[-1] not in KEPT)
    package.writestr('superseded.txt', ''.join(n + '\n' for n in superseded))
    listed.append('superseded.txt')
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<package version="1000">',
             '  <kit name="MoonRayForModo" version=%s restart="YES">' % quoteattr(args.version)]
    lines += ['    <source target=%s>%s</source>' % (quoteattr(PREFIX + path), escape(path)) for path in listed]
    lines += ['  </kit>',
              '  <message>Thank you for installing MoonRay for Modo %s. Use your silicon!</message>'
              % escape(args.version),
              '</package>', '']
    package.writestr('index.xml', '\n'.join(lines))
staged.replace(target)
digest = hashlib.sha256(target.read_bytes()).hexdigest()
print('%s: %d files, %d MB' % (target, len(listed), target.stat().st_size // 2 ** 20))
print(digest + '  ' + target.name)
