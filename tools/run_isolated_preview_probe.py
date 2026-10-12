"""Run an existing preview probe without writing into its hard-coded primary checkout."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('probe', choices=['live_cost','modes','restarts','draft_events','draft_region','draft_off','playblast','output_stop','compositor','stop_finishes'])
parser.add_argument('--runtime', required=True, type=Path)
parser.add_argument('--profile', required=True)
parser.add_argument('--results')
parser.add_argument('--kit-source', type=Path)
parser.add_argument('--timeout', type=int, default=300)
args = parser.parse_args()
if args.results and not args.results.replace('-', '').replace('_', '').isalnum():
    parser.error('Results name must contain only letters, numbers, hyphens and underscores')
source = (root / 'tools' / ('probe_' + args.probe + '.py')).read_text(encoding='utf-8')
source, count = re.subn(r'^root = pathlib.Path.*$', lambda _: 'root = pathlib.Path(' + repr(str(root)) + ')', source, count=1, flags=re.M)
if count != 1:
    raise SystemExit('Probe root declaration was not found')
# Match only the probes known native runtime constants, never a user scene path.
source = re.sub(r"root / 'runtime/steady-[^']+'", lambda _: 'pathlib.Path(' + repr(str(args.runtime.resolve())) + ')', source)
if args.results:
    source = re.sub(r"^out = root / 'test-results/[^']+'", lambda _: "out = root / 'test-results/" + args.results + "'", source, count=1, flags=re.M)
environment = dict(os.environ)
environment['MOONRAY_PROBE_RUNTIME'] = str(args.runtime.resolve())
environment.setdefault('MOONRAY_MODO_PREFERENCES', 'TestPreviewAstraLS')
with tempfile.NamedTemporaryFile(mode='w', suffix='.py', prefix='probe_astra_temp_', dir=str(root / 'tools'), encoding='utf-8', delete=False) as held:
    held.write(source)
    generated = Path(held.name)
try:
    result = subprocess.run([sys.executable, str(root / 'tools/launch_gui_probe.py'), generated.name,
                             '--profile', args.profile, '--wait', '--timeout', str(args.timeout)] +
                            (['--kit-source', str(args.kit_source.resolve())] if args.kit_source else []), env=environment)
finally:
    # This exact temporary file was created by this invocation in the worktree's tools directory.
    if generated.resolve().parent != (root / 'tools').resolve():
        raise RuntimeError('Unexpected probe location')
    generated.unlink()
sys.exit(result.returncode)
