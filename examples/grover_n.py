"""Real-world stress test: Grover's algorithm from github.com/kkoci/Qshelf
(packages/grover), estimated with guppy_estimand's opt-in upper_bound /
loop_trip_counts mode -- now including CallIndirect support (2026-09-07),
which resolves this file's last remaining blocker. See CLAUDE.md
"CallIndirect support" for the full writeup.

Short version: `oracle` and `diffuser` both use `with control(qs[0], qs[1]):
x(qs[2])` (guppy's controlled-operation modifier), which compiles to
LoadFunc + CallIndirect. Before this pass, guppy_estimand refused ANY
CallIndirect outright, so Grover could not be estimated at all. Now,
CallIndirect is resolved when its function operand traces to a LoadFunc
with a statically known target (verified true here by hand) -- reusing,
not duplicating, the call-following machinery built for `qft`'s
`discard_array` calls.

This example needs 8 distinct loop trip counts (not just one): the
array-comprehension TailLoop for register allocation, discard_array's own
internal loop, four `for i in range(3)` loops inside `diffuser`, one
`for i in range(3)` register-prep loop inside `grover_search`, and --
critically -- the REAL `for _ in range(iterations)` loop inside
`grover_search`. That real iterations loop was distinguished from the
similar-looking register-prep loop empirically (by varying each candidate
header and observing which one scales the toffoli count), not by guessing
from node-ID order -- see CLAUDE.md for the exact technique.

Also note (an incidental finding while hand-verifying this example, kept
here because it's non-obvious): `oracle` and `diffuser` are plain `@guppy`
functions (not `@guppy.comptime`, which disallows the `control` modifier),
so `marked`'s bit-conditions (`if (marked >> k) & 1 == 0: ...`) are NOT
compile-time-eliminated the way qft's `@guppy.comptime` loops are -- each
compiles to a genuine runtime Conditional, and the upper-bound walker
correctly takes each branch's cost regardless of the actual known bit
value. This is why `oracle[5]` in isolation reports clifford=8, not
clifford=4 (a naive count assuming the "obviously true/false" branches get
dropped).
"""

import re

from guppylang import guppy
from guppylang.std.builtins import array
from guppylang.std.quantum import discard_array, qubit

from _qshelf_grover import grover_search, optimal_iterations
from guppy_estimand import estimate
from guppy_estimand.gate_counts import LoopTripCountMissing, extract_gate_counts

MARKED = 5
ITERATIONS = optimal_iterations(n_items=8, n_marked=1)  # 2, for N=8/1 marked


@guppy
def main() -> None:
    qs = array(qubit() for _ in range(3))
    grover_search[MARKED, ITERATIONS](qs)
    discard_array(qs)


def _estimate_with_discovered_trip_counts(compiled):
    """Discovers every loop header via LoopTripCountMissing, then
    identifies the one real `iterations` header among them empirically:
    supplying a large trip count (50) to each candidate in turn and
    checking which one is the only one that scales the toffoli count past
    a small threshold (register-prep and array-allocation loops never
    touch toffoli at all -- only oracle/diffuser's controlled-X calls,
    reached once per real iteration, do)."""
    found: dict[int, int] = {}
    headers: list[int] = []
    for _ in range(30):
        try:
            estimate(compiled, scheme="beverland", data_d=17, upper_bound=True, loop_trip_counts=found)
            break
        except LoopTripCountMissing as e:
            m = re.search(r"HUGR node (\d+)", str(e))
            assert m
            header = int(m.group(1))
            headers.append(header)
            found[header] = 3
    else:
        raise AssertionError("did not converge on all loop headers")

    iterations_header = None
    for candidate in headers:
        trial = {h: (50 if h == candidate else 3) for h in headers}
        gate_counts, _ = extract_gate_counts(compiled, upper_bound=True, loop_trip_counts=trial)
        if gate_counts.toffoli > 10:
            iterations_header = candidate
            break
    assert iterations_header is not None, "could not identify the iterations loop"

    trip_counts = {h: (ITERATIONS if h == iterations_header else 3) for h in headers}
    return estimate(compiled, scheme="beverland", data_d=17, upper_bound=True, loop_trip_counts=trip_counts)


if __name__ == "__main__":
    print(f"=== Grover's algorithm, N=8, marked={MARKED}, iterations={ITERATIONS} ===")
    print("fully idiomatic qshelf source (incl. `with control(...):`), zero workarounds")
    result = _estimate_with_discovered_trip_counts(main.compile())
    print(result)
