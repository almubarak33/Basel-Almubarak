"""apex_engine - the canonical APEX Focus research engine (interface: ENGINE_SPEC.md).

This is engine_b.py, the fast numpy / numba port of apex/APEX_Focus_original.pine.  It was reconciled against the
independent pure-Python reference port engine_a.py by test_parity.py (every dataset, a parameter matrix covering
every branch, short / synthetic charts and fuzzed simulate() scenarios: bit-identical results).  Research code
imports this module, never engine_a / engine_b directly; re-run `python3 test_parity.py` after touching either port.
"""
from engine_b import *  # canonical fast engine
from engine_b import Params, run, simulate, features  # explicit re-exports (the ENGINE_SPEC public interface)
