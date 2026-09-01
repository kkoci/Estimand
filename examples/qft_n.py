"""Real-world stress test: QFT from github.com/kkoci/Qshelf (packages/qft),
estimated with guppy_estimand's opt-in upper_bound / loop_trip_counts mode
-- now including TailLoop support (2026-09-06), which resolves this file's
last remaining workaround. See CLAUDE.md "TailLoop support" for the full
writeup. Short version, across three passes of this same stress test:

- Pass 1 found that QFT's own structure needs no bounded-mode support at
  all (guppylang fully unrolls its two `for` loops at compile time for a
  fixed register size) -- but that `discard_array(qs)` and `qft` itself
  (at 4+ qubits) compile to calls to *separately-defined* functions,
  silently invisible before any fix.
- Pass 2 (call-following) resolved that: both are now followed and walked,
  using the real, idiomatic `discard_array(qs)` call, across the full
  `n=2..6` range -- but still required a literal `array(qubit(), qubit(),
  ...)` instead of qshelf's own `array(qubit() for _ in range(n))`
  idiom, which compiles to a `TailLoop` node call-following didn't touch.
- **Pass 3 (this one): the array-comprehension idiom is now supported
  too.** `estimate()` below uses qshelf's `qft` completely unmodified --
  the real `array(qubit() for _ in range(n))` construction AND the real
  `discard_array(qs)` call, with NO workarounds anywhere -- across the
  full `n=2..6` range, matching the same closed-form formula verified in
  pass 2 exactly.

TailLoop's trip count (e.g. `3` for `range(3)`) is NOT auto-derived, even
though `n` is compile-time-known here -- investigated and found to require
interpreting compiler-specific arithmetic (which literal `Const` among
several represents the true iteration bound) rather than reading one
structurally-guaranteed field, so it's out of scope for this pass (see
CLAUDE.md). Every TailLoop needs an explicit caller-supplied trip count,
exactly like a `while`-loop -- discovered below via `LoopTripCountMissing`,
the same mechanism used throughout this project.

Each register size is a real, literal function (not dynamically
generated) -- guppylang's parser needs actual source on disk.
"""

import re

from guppylang import guppy
from guppylang.std.builtins import array
from guppylang.std.quantum import discard_array, qubit

from _qshelf_qft import qft
from guppy_estimand import estimate
from guppy_estimand.gate_counts import LoopTripCountMissing


@guppy
def main_n2() -> None:
    qs = array(qubit() for _ in range(2))
    qft(qs)
    discard_array(qs)


@guppy
def main_n3() -> None:
    qs = array(qubit() for _ in range(3))
    qft(qs)
    discard_array(qs)


@guppy
def main_n4() -> None:
    qs = array(qubit() for _ in range(4))
    qft(qs)
    discard_array(qs)


@guppy
def main_n5() -> None:
    qs = array(qubit() for _ in range(5))
    qft(qs)
    discard_array(qs)


@guppy
def main_n6() -> None:
    qs = array(qubit() for _ in range(6))
    qft(qs)
    discard_array(qs)


def _estimate_with_discovered_trip_counts(compiled, n: int):
    """Discovers every loop header (the TailLoop from `array(qubit() for _
    in range(n))`, plus discard_array's own internal loop) via
    LoopTripCountMissing and supplies a trip count for each. The TailLoop's
    real trip count IS `n` (verified by hand -- see CLAUDE.md); the
    discard_array header's value doesn't affect the reported gate counts
    at all (its only quantum op, QFree, is zero-cost), so `n` is used
    there too, out of convenience, not because it's known to be correct
    for that loop specifically."""
    found: dict[int, int] = {}
    for _ in range(10):
        try:
            return estimate(
                compiled, scheme="beverland", data_d=17, upper_bound=True, loop_trip_counts=found
            )
        except LoopTripCountMissing as e:
            m = re.search(r"HUGR node (\d+)", str(e))
            assert m
            found[int(m.group(1))] = n
    raise AssertionError("did not converge on all loop headers")


if __name__ == "__main__":
    print("=== QFT on n=2..6 qubits, fully idiomatic qshelf source, zero workarounds ===")
    for n, main in [(2, main_n2), (3, main_n3), (4, main_n4), (5, main_n5), (6, main_n6)]:
        result = _estimate_with_discovered_trip_counts(main.compile(), n)
        print(f"--- n={n} ---")
        print(result)
        print()
