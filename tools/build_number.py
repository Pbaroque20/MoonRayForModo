"""The kit's build number: this branch's commits so far, "+" where the kit has changes not yet committed.

build_number.py <kit folder> writes it into that kit, for its About window. Release packages get theirs as they are made."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILE = 'python/moonray_modo/BUILD.txt'


def number():
    git = lambda *args: subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()
    return git('rev-list', '--count', 'HEAD') + ('+' if git('status', '--porcelain', '--', 'kit/MoonRayForModo') else '')


def main():
    target = Path(sys.argv[1]) / FILE
    target.write_text(number() + '\n', encoding='ascii')
    print(target, number())


if __name__ == '__main__':
    main()
