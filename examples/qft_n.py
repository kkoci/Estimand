"""Real-world stress test: QFT from github.com/kkoci/Qshelf (packages/qft),
estimated with guppy_estimand's opt-in upper_bound / loop_trip_counts mode.

See CLAUDE.md "Real-world stress test" for the full writeup. Short version:

- `qft` is written generically over the register size (`@guppy.comptime`,
  `array[qubit, n]`). guppylang 1.0.2 fully unrolls its `for` loops at
  compile time -- so, once compiled, it needs NO bounded-control-flow
  support at all (no CFG/Conditional survive in its own body). This
  example's flagship result (below) needed `upper_bound=True` only because
  of unrelated array-handling machinery (Conditional nodes from qubit
  array indexing), not because of qft's own two nested `for` loops.
- BUT: this stress test found two real, previously-undiscovered problems
  in guppy_estimand -- not in qft. Both are demonstrated below, honestly,
  rather than avoided to make this example look cleaner than the tool
  currently is:

  1. `array(qubit() for _ in range(n))` -- the exact idiomatic array
     construction qshelf's own examples use -- compiles to a `TailLoop`
     node, which guppy_estimand explicitly does not support (raises
     UnsupportedControlFlowShape). Worked around below by using a literal
     `array(qubit(), qubit(), ...)` instead.
  2. `discard_array(qs)` -- again, the exact idiomatic pattern used by
     EVERY qshelf example/test to free a qubit array -- compiles to a call
     to a separately-defined function (`guppylang.std.quantum.discard_array`)
     rather than being inlined. Before this stress test, guppy_estimand
     silently ignored calls to non-inlined functions, returning a
     near-zero gate count with no error. This is now fixed to fail loudly
     instead (`CallNotSupported`) -- but there is still no way to actually
     see inside such a call, so this example works around it too, by
     discarding each qubit individually instead of via the array-level
     helper.
  3. (Not just a workaround-away detail): `qft` ITSELF gets compiled as a
     separately-called function, not inlined, once the register is 4+
     qubits (verified: inlined for n<=3, not for n>=4, with no other code
     change) -- so even with both workarounds above, this example is
     capped at n=3. A real, `CallNotSupported`-raising 4-qubit attempt is
     demonstrated at the bottom of this file's `__main__` block, run for
     real, not hypothesized.

None of this is qft's fault -- it's a well-written, generically-sized
algorithm. It is exactly the kind of real code this stress test was meant
to run guppy_estimand against, and it found real, previously-unknown gaps.
"""

from guppylang import guppy
from guppylang.std.builtins import array
from guppylang.std.quantum import discard, qubit

from _qshelf_qft import qft
from guppy_estimand import estimate
from guppy_estimand.gate_counts import CallNotSupported, UnsupportedControlFlowShape

N = 3  # capped at 3 -- qft itself is no longer inlined for n>=4, see module docstring


@guppy
def qft_n() -> None:
    # Literal array construction (NOT the `array(qubit() for _ in range(N))`
    # comprehension idiom qshelf's own examples use -- that compiles to a
    # TailLoop, unsupported; see module docstring finding 1).
    qs = array(qubit(), qubit(), qubit())
    qft(qs)
    # Individual discard() per qubit (NOT discard_array(qs), the idiomatic
    # qshelf pattern -- that's a call to a non-inlined function,
    # CallNotSupported; see module docstring finding 2).
    q0, q1, q2 = qs
    discard(q0)
    discard(q1)
    discard(q2)


if __name__ == "__main__":
    print("=== Working result: QFT on 3 qubits (literal array, individual discard) ===")
    result = estimate(
        qft_n.compile(), scheme="beverland", data_d=17, upper_bound=True, loop_trip_counts={}
    )
    print(result)

    print()
    print("=== Documented finding 1: qshelf's own array(... for _ in range(n)) idiom ===")

    @guppy
    def qft_n_idiomatic_array() -> None:
        qs = array(qubit() for _ in range(N))
        qft(qs)
        q0, q1, q2 = qs
        discard(q0)
        discard(q1)
        discard(q2)

    try:
        estimate(qft_n_idiomatic_array.compile(), upper_bound=True, loop_trip_counts={})
        print("(unexpectedly succeeded)")
    except UnsupportedControlFlowShape as e:
        print(f"UnsupportedControlFlowShape (expected): {e}")

    print()
    print("=== Documented finding 2: qshelf's own discard_array(qs) idiom ===")

    from guppylang.std.quantum import discard_array

    @guppy
    def qft_n_idiomatic_discard() -> None:
        qs = array(qubit(), qubit(), qubit())
        qft(qs)
        discard_array(qs)

    try:
        estimate(qft_n_idiomatic_discard.compile(), upper_bound=True, loop_trip_counts={})
        print("(unexpectedly succeeded)")
    except CallNotSupported as e:
        print(f"CallNotSupported (expected): {e}")

    print()
    print("=== Documented finding 3: qft itself stops being inlined at n=4 ===")

    @guppy
    def qft_4() -> None:
        qs = array(qubit(), qubit(), qubit(), qubit())
        qft(qs)
        q0, q1, q2, q3 = qs
        discard(q0)
        discard(q1)
        discard(q2)
        discard(q3)

    try:
        estimate(qft_4.compile(), upper_bound=True, loop_trip_counts={})
        print("(unexpectedly succeeded)")
    except CallNotSupported as e:
        print(f"CallNotSupported (expected): {e}")
