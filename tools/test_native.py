"""Run the built native renderer component tests without rebuilding."""
from pathlib import Path
import os
import subprocess

root = Path(__file__).resolve().parents[1]
build = root / 'build/native-renderer-avx'
bin_dir = root / 'toolchain/msys64/ucrt64/bin'
environment = os.environ.copy()
environment['PATH'] = os.pathsep.join([str(build / 'bin'), str(build / 'log4cplus/bin'),
                                     str(bin_dir), environment.get('PATH', '')])
result = subprocess.run([str(bin_dir / 'ctest.exe'), '--test-dir', str(build), '--output-on-failure'],
                        env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW)
(build / 'test.log').write_text(result.stdout, encoding='utf-8')
print(result.stdout)
raise SystemExit(result.returncode)
