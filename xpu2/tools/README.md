# XPU2 tools kept outside the build

Copies of the scripts that live in the git-ignored MoonRayForModo-xpu2/test-results folder, kept here so they are not lost:

- kit/: the private XPU2 kit (build_xpu2_kit.py builds it from the installed standard kit and an XPU2 session; install_xpu2.py installs it with Modo closed; check_xpu2_session_qt.py is the headless Qt check).
- modo-cl/: headless Modo export and comparison (setup_profile, run_cl, export_probe, preview_probe, timing_probe for where the kit's time goes, compare, run_watched), and the Modo crash debugger (debug_modo.py; never gdb, whose JIT breakpoint on nvgpucomp64 ends Modo).

They run from test-results; the copies here are for safekeeping.
