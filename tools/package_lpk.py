"""Make a Modo package (.lpk) of a release: the kit and its Windows runtime in one file, which Modo installs into
the user's Kits folder when it is dropped onto a viewport, in place of unpacking two ZIPs and copying folders by hand.

package_lpk.py <version> [--with-content]

Reads dist/release-<version>/MoonRayForModo-<version>-kit.zip and -windows-runtime.zip (made by
tools/package_development_release.py) and writes dist/release-<version>/MoonRayForModo-<version>.lpk. An .lpk is a ZIP
whose index.xml names the kit and lists each file with where it goes inside the kit's folder. --with-content adds the
example scenes of the content ZIP to the asset library as well (about 300 MB more).

It replaces an older install: Modo only adds and overwrites, so the package also lists its own files (installed.txt,
in the kit's folder), and the kit, the first time it starts after, moves aside what an older version left that the
list does not name (stale_files.py). On install Modo shows the package's message: thanks, and to restart.
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
                    package.writestr(zipfile.ZipInfo(inside, info.date_time), data.read(), zipfile.ZIP_DEFLATED)
                listed.append(inside)
    if 'index.cfg' not in seen:
        raise SystemExit('The kit ZIP has no index.cfg')
    # The list of what this version installs, which the kit reads to move aside what an older one left (stale_files.py).
    package.writestr('installed.txt', '%s\n%s\n' % (args.version, '\n'.join(sorted(listed + ['installed.txt']))))
    listed.append('installed.txt')
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<package version="1000">',
             '  <kit name="MoonRayForModo" version=%s>' % quoteattr(args.version)]
    lines += ['    <source target=%s>%s</source>' % (quoteattr(path), escape(path)) for path in listed]
    lines += ['  </kit>',
              '  <message>Thank you for installing MoonRay for Modo %s. Use your silicon! Restart Modo to load it.</message>'
              % escape(args.version),
              '</package>', '']
    package.writestr('index.xml', '\n'.join(lines))
staged.replace(target)
digest = hashlib.sha256(target.read_bytes()).hexdigest()
print('%s: %d files, %d MB' % (target, len(listed), target.stat().st_size // 2 ** 20))
print(digest + '  ' + target.name)
