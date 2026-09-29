"""Repair ISPC 1.31's unescaped Windows paths before Ninja reads its depfile."""
from pathlib import Path
import subprocess
import sys


def make_escape(path):
    return path.replace('\\', '/').replace('$', '$$').replace('#', '\\#').replace(' ', '\\ ')


def repair(depfile, target):
    # ISPC emits one filename per continuation line, with no make escaping.
    # Preserve every dependency and reject an unexpected format instead of
    # silently making header edits invisible to subsequent builds.
    content = depfile.read_text(encoding='utf-8')
    body = content.split(': ', 1)[1]
    dependencies = []
    for line in body.splitlines():
        path = line.strip()
        if path.endswith('\\'):
            path = path[:-1].rstrip()
        if not path:
            continue
        if not Path(path).is_file():
            raise RuntimeError('Unexpected ISPC dependency filename: ' + path)
        dependencies.append(make_escape(path))
    if not dependencies:
        raise RuntimeError('ISPC did not report any source dependencies')
    depfile.write_text(make_escape(target) + ': ' + ' \\\n '.join(dependencies) + '\n', encoding='utf-8')


if __name__ == '__main__':
    command = sys.argv[1:]
    result = subprocess.run(command)
    if result.returncode == 0 and '-MF' in command:
        repair(Path(command[command.index('-MF') + 1]), command[command.index('-MT') + 1])
    raise SystemExit(result.returncode)
