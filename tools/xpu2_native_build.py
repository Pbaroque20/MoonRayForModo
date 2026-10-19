"""Build the active XPU2 stages through one isolated compiler/link pipeline."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from xpu2.native_build import main
if __name__=='__main__':raise SystemExit(main())
