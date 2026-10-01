"""Run one deferred numerical/export group; never launches Modo or a renderer."""
import argparse
import io
import json
from pathlib import Path
import sys
import unittest

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'tests'))
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('feature',choices=['materials','textures','geometry','environments','rendering','all'])
args=parser.parse_args()
import test_cpu_features
suite=unittest.defaultTestLoader.loadTestsFromModule(test_cpu_features) if args.feature=='all' else \
      unittest.defaultTestLoader.loadTestsFromTestCase(getattr(test_cpu_features,args.feature.capitalize()))
log=io.StringIO()
result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
folder=root/'test-results/cpu-features'; folder.mkdir(parents=True,exist_ok=True)
(folder/(args.feature+'-export.json')).write_text(json.dumps({'passed':result.wasSuccessful(),
    'count':result.testsRun,'level':'numerical/export only; no host or renderer parity', 'log':log.getvalue()},indent=2))
print(log.getvalue())
raise SystemExit(0 if result.wasSuccessful() else 1)
