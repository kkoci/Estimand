"""Real-world stress test: QFT from github.com/kkoci/Qshelf (packages/qft),
estimated with guppy_estimand's opt-in upper_bound / loop_trip_counts mode
-- now including call-following (2026-09-05), which resolved this file's
previous headline finding. See CLAUDE.md "Call-following" for the full
writeup. Short version:

- `qft` is written generically over the register size (`@guppy.comptime`,
  `array[qubit, n]`) and, once compiled, needs NO bounded-control-flow
  support at all -- guppylang fully unrolls its two `for` loops at compile
  time. `upper_bound=True` is needed here only because of unrelated
  array-handling machinery (Conditional nodes from qubit array indexing),
  not because of qft's own loops.
- The first pass of this stress test (before call-following existed) found
  that `discard_array(qs)` -- the idiomatic pattern used by EVERY qshelf
  example/test to free a qubit array -- compiles to a call to a
  *separately-defined* function, and that `qft` ITSELF stops being inlined
  once the register hits 4+ qubits. Before any fix, both were silently
  invisible (near-zero gate counts, no error); a stopgap (`CallNotSupported`)
  then made them fail loudly instead of silently.
- **Now (this pass): both are actually followed and walked, not just
  refused.** `estimate()` recurses into a called function's body (including
  discard_array's own internal loop, which needs its own trip count) using
  the same traversal that walks the caller. Demonstrated below across the
  FULL n=2..6 range using the real, idiomatic `discard_array(qs)` call --
  no workaround needed for that anymore.
- **Still unresolved, and NOT what call-following was for**: qshelf's own
  `array(qubit() for _ in range(n))` array-*comprehension* idiom compiles to
  a `TailLoop` node, which is a completely separate, still-unsupported HUGR
  shape (raises `UnsupportedControlFlowShape`). This example works around
  it with a literal `array(qubit(), qubit(), ...)` -- demonstrated
  explicitly failing at the bottom of `__main__`, not silently avoided.

Each register size below is a real, literal function (not dynamically
generated): guppylang's parser needs actual source on disk
(`inspect.getsourcelines`) -- an exec()'d/dynamically-built function body
fails to compile even with an explicit synthetic filename passed to
`compile()`, confirmed by hand while building this file (see CLAUDE.md
"HUGR quirks" for the original, narrower version of this finding).

None of this is qft's fault -- it's a well-written, generically-sized
algorithm. It is exactly the kind of real code this stress test was meant
to run guppy_estimand against, and across two passes it has found and fixed
one real, serious gap (call-following) while surfacing another
(the array-comprehension TailLoop shape) that remains open.
"""

import re

from guppylang import guppy
from guppylang.std.builtins import array
from guppylang.std.quantum import discard_array, qubit

from _qshelf_qft import qft
from guppy_estimand import estimate
from guppy_estimand.gate_counts import LoopTripCountMissing, UnsupportedControlFlowShape


@guppy
def main_n2() -> None:
    qs = array(qubit(), qubit())
    qft(qs)
    discard_array(qs)


@guppy
def main_n3() -> None:
    qs = array(qubit(), qubit(), qubit())
    qft(qs)
    discard_array(qs)


@guppy
def main_n4() -> None:
    qs = array(qubit(), qubit(), qubit(), qubit())
    qft(qs)
    discard_array(qs)


@guppy
def main_n5() -> None:
    qs = array(qubit(), qubit(), qubit(), qubit(), qubit())
    qft(qs)
    discard_array(qs)


@guppy
def main_n6() -> None:
    qs = array(qubit(), qubit(), qubit(), qubit(), qubit(), qubit())
    qft(qs)
    discard_array(qs)


def _estimate_with_discovered_trip_counts(compiled):
    """Discovers every loop header via LoopTripCountMissing and supplies a
    trip count for each, then returns the final estimate(). discard_array's
    own internal loop trip count doesn't affect the reported gate counts at
    all here (its only quantum op, QFree, is classified as zero-cost) --
    verified by hand to give identical results for trip counts 1, 4, and
    100 -- so any non-negative value works; 10 is used below as an
    arbitrary placeholder, not a claim that it's the "correct" count."""
    found: dict[int, int] = {}
    for _ in range(10):
        try:
            return estimate(
                compiled, scheme="beverland", data_d=17, upper_bound=True, loop_trip_counts=found
            )
        except LoopTripCountMissing as e:
            m = re.search(r"HUGR node (\d+)", str(e))
            assert m
            found[int(m.group(1))] = 10
    raise AssertionError("did not converge on all loop headers")


if __name__ == "__main__":
    print("=== QFT on n=2..6 qubits, real idiomatic discard_array(qs), literal array ===")
    for n, main in [(2, main_n2), (3, main_n3), (4, main_n4), (5, main_n5), (6, main_n6)]:
        result = _estimate_with_discovered_trip_counts(main.compile())
        print(f"--- n={n} ---")
        print(result)
        print()

    print("=== Still open: qshelf's own array(qubit() for _ in range(n)) idiom ===")
    print("(a genuinely different HUGR shape -- TailLoop -- unrelated to call-following)")

    @guppy
    def qft_n_idiomatic_array() -> None:
        qs = array(qubit() for _ in range(4))
        qft(qs)
        discard_array(qs)

    try:
        estimate(qft_n_idiomatic_array.compile(), upper_bound=True, loop_trip_counts={})
        print("(unexpectedly succeeded)")
    except UnsupportedControlFlowShape as e:
        print(f"UnsupportedControlFlowShape (still expected): {e}")
