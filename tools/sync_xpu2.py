"""Keep xpu2-0.5 (the 0.5 kit with MoonRay XPU2, on xpu2-foundation) current with MoonLightIPR (origin).

Run from the xpu2-0.5 worktree (MoonRayForModo-xpu2-0.5), its working tree clean:

    python tools/sync_xpu2.py            merge origin/MoonLightIPR, run the tests, push to xpu2-foundation
    python tools/sync_xpu2.py --no-push  the same without the push

Work without XPU2 in it goes to MoonLightIPR (origin) and comes here by this merge; XPU2's own work (xpu2/, its kit
files, the preview session) is committed here alone. The merge stops at a conflict, left for a person to settle; a
failing test stops it before the push. The tests read MoonRay's source from upstream/ (not in git), linked here from
the main checkout (MoonRayForModo) where this worktree has none. At the 0.5 release, xpu2-0.5 is merged into
MoonLightIPR once."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT.parent / 'MoonRayForModo'


def git(*args, check=True):
    done = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True)
    if check and done.returncode:
        raise SystemExit('git %s failed:\n%s%s' % (' '.join(args), done.stdout, done.stderr))
    return done.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--no-push', action='store_true', help='merge and test, but do not push')
    args = parser.parse_args()
    if git('rev-parse', '--abbrev-ref', 'HEAD') != 'xpu2-0.5':
        raise SystemExit('Run this on the xpu2-0.5 branch (its worktree, MoonRayForModo-xpu2-0.5).')
    if git('status', '--porcelain', '--untracked-files=no'):
        raise SystemExit('The working tree has changes: commit or put them aside first.')
    git('fetch', 'origin')
    git('fetch', 'xpu2-foundation')
    behind = git('rev-list', '--count', 'HEAD..xpu2-foundation/xpu2-0.5', check=False)
    if behind and behind != '0':
        raise SystemExit('xpu2-foundation/xpu2-0.5 has %s commits this branch lacks: merge them first.' % behind)
    new = git('rev-list', '--count', 'HEAD..origin/MoonLightIPR')
    if new == '0':
        print('xpu2-0.5 already has every MoonLightIPR commit.')
    else:
        print('Merging %s MoonLightIPR commits.' % new)
        merged = subprocess.run(['git', 'merge', '--no-edit', 'origin/MoonLightIPR'], cwd=ROOT, capture_output=True, text=True)
        if merged.returncode:
            print(merged.stdout + merged.stderr)
            raise SystemExit('The merge stopped at a conflict: settle it here, commit, and run this again.')
    # MoonRay's source for the tests that read it (git-ignored; a link to the main checkout's).
    upstream = ROOT / 'upstream'
    if not upstream.exists() and (MAIN / 'upstream').is_dir():
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(upstream), str(MAIN / 'upstream')], capture_output=True)
    python = MAIN / 'toolchain/msys64/ucrt64/bin/python.exe'
    tests = subprocess.run([str(python if python.is_file() else sys.executable), '-m', 'unittest', 'discover', '-s', 'tests', '-q'],
                           cwd=ROOT, capture_output=True, text=True)
    print((tests.stdout + tests.stderr).strip().splitlines()[-1] if (tests.stdout + tests.stderr).strip() else 'no test output')
    if tests.returncode:
        print(tests.stderr[-4000:])
        raise SystemExit('Tests failed: nothing pushed.')
    if args.no_push:
        print('Merged and tested; not pushed (--no-push).')
        return
    pushed = subprocess.run(['git', 'push', 'xpu2-foundation', 'xpu2-0.5'], cwd=ROOT, capture_output=True, text=True)
    print((pushed.stdout + pushed.stderr).strip())
    if pushed.returncode:
        raise SystemExit('The push was refused (see above).')


if __name__ == '__main__':
    main()
