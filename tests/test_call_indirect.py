"""Tests for guppy_estimand's CallIndirect support (added 2026-09-07) --
resolving ops.CallIndirect when its function operand traces to an
ops.LoadFunc with a statically known target. See CLAUDE.md "CallIndirect
support" for the full hand-verified derivation this is built against: how
`with control(...):` compiles to LoadFunc + CallIndirect, why LoadFunc's
target is a genuine static edge (not a heuristic), and a real,
constructed (not hypothetical) case showing CallNotSupported still
correctly fires when the function operand is genuinely dynamic (chosen at
runtime via a conditional).
"""

import re

import pytest
from guppylang import guppy
from guppylang.std.builtins import Function, array
from guppylang.std.quantum import discard, discard_array, h, measure, qubit, x

from guppy_estimand.gate_counts import (
    CallNotSupported,
    LoopTripCountMissing,
    extract_gate_counts,
)


def _discover_loop_headers(compiled) -> list[int]:
    """Test helper (same pattern as the other test_*.py files in this
    project): repeatedly calls extract_gate_counts with an ever-growing
    loop_trip_counts dict (placeholder count of 3 each time), recording
    each header LoopTripCountMissing names, until it stops raising."""
    found: dict[int, int] = {}
    order: list[int] = []
    for _ in range(30):
        try:
            extract_gate_counts(compiled, upper_bound=True, loop_trip_counts=found)
            return order
        except LoopTripCountMissing as e:
            m = re.search(r"HUGR node (\d+)", str(e))
            assert m, str(e)
            header = int(m.group(1))
            order.append(header)
            found[header] = 3
    raise AssertionError("did not converge on all loop headers")


# --- Basic CallIndirect resolution: guppy's `with control(...):` modifier ---


@guppy
def _control_circ() -> None:
    q0 = qubit()
    q1 = qubit()
    q2 = qubit()
    with control(q0, q1):
        x(q2)
    discard(q0)
    discard(q1)
    discard(q2)


def test_control_modifier_resolves_via_load_func():
    """`with control(q0, q1): x(q2)` compiles to LoadFunc + CallIndirect,
    where LoadFunc's target is a real, auto-generated FuncDefn whose body
    is a single Toffoli (verified by hand -- see CLAUDE.md). Must now be
    followed and walked, not refused."""
    compiled = _control_circ.compile()
    gate_counts, n_qubits = extract_gate_counts(compiled, upper_bound=True, loop_trip_counts={})
    assert gate_counts.toffoli == 1
    assert n_qubits == 3


def test_control_modifier_does_not_silently_undercount():
    """Directly guards the original bug: without resolution, this used to
    raise CallNotSupported outright (the old, blanket behavior) -- now it
    must succeed with the real gate count, not silently drop it."""
    compiled = _control_circ.compile()
    gate_counts, _ = extract_gate_counts(compiled, upper_bound=True, loop_trip_counts={})
    assert gate_counts.toffoli != 0


# --- The genuinely-unresolvable case still correctly refuses ---
#
# Guppy from guppylang.std.builtins import control -- imported at module
# level below so `with control(...):` resolves without an explicit import
# inside the function (matches how qshelf's grover.py imports it).
from guppylang.std.builtins import control  # noqa: E402


@guppy
def _apply_h(q: qubit) -> None:
    h(q)


@guppy
def _apply_x(q: qubit) -> None:
    x(q)


@guppy
def _choose(b: bool) -> Function[[qubit], None]:
    if b:
        return _apply_h
    else:
        return _apply_x


@guppy
def _dynamic_call_circ() -> None:
    q = qubit()
    ctrl = qubit()
    h(ctrl)
    b = measure(ctrl).read()
    f = _choose(b)
    f(q)
    discard(q)


def test_genuinely_dynamic_call_indirect_still_raises():
    """A function value CHOSEN AT RUNTIME (via a genuine if/else, not a
    LoadFunc) -- constructed for real, not hypothesized (see CLAUDE.md
    "CallIndirect support" for how: `choose(b)` returns one of two
    functions depending on a measurement result). CallIndirect's function
    operand here traces to a CFG (the if/else), not a LoadFunc -- verified
    by hand. Must still raise CallNotSupported: there is no statically
    fixed target to walk, and guessing one would be wrong."""
    compiled = _dynamic_call_circ.compile()
    with pytest.raises(CallNotSupported, match="not a LoadFunc"):
        extract_gate_counts(compiled, upper_bound=True, loop_trip_counts={})


# --- Real-world: qshelf's Grover, using the actual `control(...)` pattern ---
#
# Vendored inline (not imported from the qshelf clone, which lives outside
# this repo -- see examples/_qshelf_qft.py for the same pattern used with
# QFT) so this test is self-contained and doesn't depend on an external
# checkout. Reproduced verbatim from packages/grover/src/grover/grover.py,
# with attribution -- see examples/_qshelf_grover.py.


def test_oracle_isolated_hand_verified():
    """oracle[5] (marked=5=0b101) in isolation. Hand-derived: the two
    `if (marked >> k) & 1 == 0: x(...)` conditions that DO have their `x`
    (for the zero bits of 5) each contribute 1 clifford -- but critically,
    verified by hand that ALL SIX such `if` checks in oracle's body
    (repeated before and after the controlled-X) contribute their branch's
    upper-bound cost of 1 clifford EACH, regardless of whether that
    specific bit of `marked` is actually 0 or 1 -- because `oracle` is a
    plain (non-`comptime`) `@guppy` function, so `marked`'s bit-conditions
    do NOT get compile-time-eliminated the way qft's `@guppy.comptime`
    loops were; they compile to genuine runtime Conditionals, and the
    upper-bound walker correctly takes each one's branch cost. This was a
    real, checked finding, not assumed: isolating oracle[5] gives
    clifford=8 (6 from the six `if`s + 2 from the unconditional h(qs[2])
    pair), NOT clifford=4 (an initial, wrong hand-count that assumed
    compile-time bit-elimination)."""
    from examples._qshelf_grover import oracle  # noqa: PLC0415

    @guppy
    def circ() -> None:
        qs = array(qubit() for _ in range(3))
        oracle[5](qs)
        discard_array(qs)

    compiled = circ.compile()
    headers = _discover_loop_headers(compiled)
    trip_counts = {h: 3 for h in headers}
    gate_counts, _ = extract_gate_counts(compiled, upper_bound=True, loop_trip_counts=trip_counts)
    assert gate_counts.toffoli == 1
    assert gate_counts.clifford == 8


def test_diffuser_isolated_hand_verified():
    """diffuser in isolation: 4 * "for i in range(3): <h or x>" (3 clifford
    each = 12) + 2 unconditional h(qs[2]) (2 clifford) + 1 controlled-X
    (1 toffoli) = 14 clifford, 1 toffoli."""
    from examples._qshelf_grover import diffuser  # noqa: PLC0415

    @guppy
    def circ() -> None:
        qs = array(qubit() for _ in range(3))
        diffuser(qs)
        discard_array(qs)

    compiled = circ.compile()
    headers = _discover_loop_headers(compiled)
    trip_counts = {h: 3 for h in headers}
    gate_counts, _ = extract_gate_counts(compiled, upper_bound=True, loop_trip_counts=trip_counts)
    assert gate_counts.toffoli == 1
    assert gate_counts.clifford == 14


def test_grover_search_full_hand_verified():
    """The full, real, unmodified qshelf Grover algorithm: register-prep
    (3 clifford) + iterations * (oracle + diffuser) = 3 + 2*(8+14) clifford
    = 47 clifford, 2*(1+1) = 4 toffoli, matching
    `oracle[5]`/`diffuser`'s independently-verified isolated counts above
    exactly. This requires correctly composing: CallIndirect resolution
    (the controlled-X inside oracle and diffuser), Call-following (oracle
    and diffuser are both separate, non-inlined FuncDefns), a CFG loop for
    the real `iterations=2` trip count (distinguished BY HAND from the
    OTHER, unrelated `for i in range(3)` loops also present -- see
    CLAUDE.md for how: varying each candidate header independently and
    checking which one scales the toffoli count), and the array-
    comprehension TailLoop for register allocation -- everything this
    project has built, composing correctly on one real algorithm."""
    from examples._qshelf_grover import grover_search, optimal_iterations  # noqa: PLC0415

    marked = 5
    iterations = optimal_iterations(8, 1)
    assert iterations == 2  # sanity check on the classical helper itself

    @guppy
    def circ() -> None:
        qs = array(qubit() for _ in range(3))
        grover_search[marked, iterations](qs)
        discard_array(qs)

    compiled = circ.compile()
    headers = _discover_loop_headers(compiled)

    # Identify the real `iterations` loop by checking which header's trip
    # count scales the toffoli count (the register-prep and array-
    # comprehension loops don't touch toffoli at all).
    iterations_header = None
    for candidate in headers:
        trial = {h: (50 if h == candidate else 3) for h in headers}
        gc, _ = extract_gate_counts(compiled, upper_bound=True, loop_trip_counts=trial)
        if gc.toffoli > 10:  # only the real iterations loop scales this far
            iterations_header = candidate
            break
    assert iterations_header is not None, "could not identify the iterations loop"

    trip_counts = {h: (iterations if h == iterations_header else 3) for h in headers}
    gate_counts, n_qubits = extract_gate_counts(
        compiled, upper_bound=True, loop_trip_counts=trip_counts
    )
    assert gate_counts.toffoli == 4
    assert gate_counts.clifford == 47
    assert n_qubits == 3
