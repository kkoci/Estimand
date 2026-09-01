"""Tests for guppy_estimand's TailLoop support (added 2026-09-06) -- the
`array(qubit() for _ in range(n))` array-comprehension idiom, used across
every qshelf package to allocate qubit registers, previously raised
UnsupportedControlFlowShape unconditionally. See CLAUDE.md "HUGR quirks" /
"TailLoop support" for the full hand-verified derivation this is built
against: the one verified TailLoop shape (a decision Conditional with
exactly 2 Cases, tag 0 = continue / tag 1 = break, determined by tracing
each Case's Output rather than assuming Case position), why trip-count
auto-derivation was investigated and NOT implemented (the bound is present
as a literal Const but not robustly locatable without interpreting
compiler-specific arithmetic), and why n_qubits IS scaled by trip count
here (unlike CFG while-loops) since array-comprehension qubits persist
into the loop-carried state rather than being freed per-iteration.

Guppy functions below are real, literal definitions (not dynamically
exec()'d per test parameter) -- guppylang's parser needs actual source on
disk (`inspect.getsourcelines`); an exec()'d function body fails to
compile even with an explicit synthetic filename (verified by hand in a
prior pass -- see CLAUDE.md "HUGR quirks" / "Real-world stress test").
"""

import re

import pytest
from guppylang import guppy
from guppylang.std.builtins import array
from guppylang.std.quantum import discard_array, h, measure, qubit, x

from guppy_estimand.gate_counts import LoopTripCountMissing, extract_gate_counts


def _discover_loop_headers(compiled) -> list[int]:
    """Test helper (same pattern as tests/test_bounded_control_flow.py and
    tests/test_call_following.py): repeatedly calls extract_gate_counts
    with an ever-growing loop_trip_counts dict (placeholder count of 1
    each time), recording each header LoopTripCountMissing names, until it
    stops raising. Returns headers in discovery order. Works uniformly for
    both CFG-loop headers and TailLoop node IDs -- both are keyed in the
    same loop_trip_counts dict."""
    found: dict[int, int] = {}
    order: list[int] = []
    for _ in range(20):
        try:
            extract_gate_counts(compiled, upper_bound=True, loop_trip_counts=found)
            return order
        except LoopTripCountMissing as e:
            m = re.search(r"HUGR node (\d+)", str(e))
            assert m, str(e)
            header = int(m.group(1))
            order.append(header)
            found[header] = 1
    raise AssertionError("did not converge on all loop headers")


# --- Basic TailLoop support ---


def test_array_comprehension_no_longer_raises_unconditionally():
    """The old behavior (before 2026-09-06): ANY TailLoop raised
    UnsupportedControlFlowShape unconditionally. This is qshelf's own
    idiomatic pattern for allocating a qubit register, used in literally
    every package -- it must now be walked, not refused outright."""

    @guppy
    def circ() -> None:
        qs = array(qubit() for _ in range(3))
        discard_array(qs)

    compiled = circ.compile()
    headers = _discover_loop_headers(compiled)
    assert len(headers) == 2  # the TailLoop itself + discard_array's own internal loop

    gate_counts, n_qubits = extract_gate_counts(
        compiled, upper_bound=True, loop_trip_counts={h: 3 for h in headers}
    )
    assert n_qubits == 3
    # No gates other than QAlloc/QFree in this minimal example -- both are
    # zero-cost by classification, so gate_counts should be all-zero.
    assert gate_counts.clifford == 0
    assert gate_counts.t == 0


def test_missing_trip_count_names_the_tail_loop_node():
    @guppy
    def circ() -> None:
        qs = array(qubit() for _ in range(3))
        discard_array(qs)

    compiled = circ.compile()
    with pytest.raises(LoopTripCountMissing, match=r"HUGR node \d+"):
        extract_gate_counts(compiled, upper_bound=True, loop_trip_counts={})


@guppy
def _circ_n1() -> None:
    qs = array(qubit() for _ in range(1))
    discard_array(qs)


@guppy
def _circ_n2() -> None:
    qs = array(qubit() for _ in range(2))
    discard_array(qs)


@guppy
def _circ_n5() -> None:
    qs = array(qubit() for _ in range(5))
    discard_array(qs)


@guppy
def _circ_n8() -> None:
    qs = array(qubit() for _ in range(8))
    discard_array(qs)


@pytest.mark.parametrize(
    ("circ", "n"), [(_circ_n1, 1), (_circ_n2, 2), (_circ_n5, 5), (_circ_n8, 8)]
)
def test_n_qubits_scales_with_trip_count_unlike_while_loops(circ, n):
    """Core semantic check, distinguishing TailLoop from CFG while-loops:
    n_qubits scales with the (correct) trip count here, because each
    iteration's qubit() call becomes part of the array (the loop-carried
    state) and survives past that iteration -- checked across several
    sizes, not just one, to rule out a coincidental match. Supplying the
    WRONG trip count (not matching the real range(n)) would silently give
    a wrong-but-plausible-looking n_qubits -- that's the caller's
    responsibility, same as any other loop trip count (see
    LoopTripCountMissing's docstring)."""
    compiled = circ.compile()
    headers = _discover_loop_headers(compiled)
    # discard_array's own internal loop trip count doesn't affect the
    # result (its only op, QFree, is zero-cost) -- use the real n for the
    # TailLoop's own header (found by checking which header, when supplied
    # n, gives n_qubits == n) and an arbitrary value for the rest.
    for candidate in headers:
        trip_counts = {h: (n if h == candidate else 1) for h in headers}
        _, n_qubits = extract_gate_counts(compiled, upper_bound=True, loop_trip_counts=trip_counts)
        if n_qubits == n:
            break
    else:
        raise AssertionError(f"no header gave n_qubits == {n}")


# --- Composition: TailLoop inside a while loop, TailLoop inside a conditional ---


@guppy
def _circ_tail_loop_in_while() -> None:
    i = 0
    while i < 2:
        qs = array(qubit() for _ in range(3))
        h(qs[0])
        discard_array(qs)
        i += 1


def test_tail_loop_inside_while_loop():
    """An array-comprehension-constructed register, built fresh each
    while-iteration and fully discarded before the next -- verified this
    is NOT the same as n_qubits = outer_trip * inner_trip (a first,
    incorrect guess this test caught): since guppy's linear typing forces
    the array to be fully consumed (discard_array) before the while loop
    can repeat, the SAME physical qubit slots are reused each outer
    iteration, exactly matching the existing while-loop convention (see
    CLAUDE.md "Bounded control flow"). The TailLoop's OWN internal
    n_qubits scaling (x3, for one full pass constructing the 3-element
    array) is what's real; the OUTER while loop does not additionally
    scale it."""
    compiled = _circ_tail_loop_in_while.compile()
    headers = _discover_loop_headers(compiled)
    assert len(headers) == 3  # outer while + TailLoop + discard_array's own loop

    from hugr import Node, ops

    hugr = compiled.modules[0]
    tailloop_header = next(h for h in headers if isinstance(hugr[Node(h)].op, ops.TailLoop))
    other_headers = [h for h in headers if h != tailloop_header]

    # Find the outer while-loop's header among `other_headers` by checking
    # which FuncDefn each belongs to: the outer while is in `main`, the
    # other is inside discard_array's separate FuncDefn.
    def _owning_funcdefn_name(header: int) -> str:
        node = Node(header)
        for n2, data in hugr.nodes():
            if type(data.op).__name__ == "CFG" and node in hugr.children(n2):
                for n3, data3 in hugr.nodes():
                    if n2 in hugr.children(n3) and type(data3.op).__name__ == "FuncDefn":
                        return data3.op.f_name
        raise AssertionError(f"could not find owning FuncDefn for header {header}")

    outer_while_header = next(
        h for h in other_headers if not _owning_funcdefn_name(h).startswith("guppylang.std.quantum")
    )
    discard_array_header = next(h for h in other_headers if h != outer_while_header)

    trip_counts = {tailloop_header: 3, outer_while_header: 2, discard_array_header: 1}
    gate_counts, n_qubits = extract_gate_counts(compiled, upper_bound=True, loop_trip_counts=trip_counts)

    # h(qs[0]) runs once per outer iteration: 2 * 1 = 2 clifford.
    assert gate_counts.clifford == 2
    # NOT outer_trip * tailloop_trip (2*3=6) -- the array is fully freed
    # within each outer iteration (guppy's linear typing forces this), so
    # the outer while-loop's existing non-scaling convention applies; only
    # the TailLoop's own internal n_qubits=3 (one full array) survives.
    assert n_qubits == 3


@guppy
def _circ_tail_loop_in_conditional() -> None:
    ctrl = qubit()
    h(ctrl)
    b = measure(ctrl)
    if b:
        qs = array(qubit(), qubit(), qubit())
        x(qs[0])
        discard_array(qs)
    else:
        qs2 = array(qubit() for _ in range(5))
        discard_array(qs2)


def test_tail_loop_inside_conditional():
    """One branch builds its array via a literal (3 qubits, 1 clifford
    gate), the other via the TailLoop-comprehension idiom (5 qubits, no
    gates) -- checks TailLoop composes correctly with the pre-existing
    conditional max-of-branches logic, in both directions (clifford count
    AND n_qubits each independently take the max of their own branch)."""
    compiled = _circ_tail_loop_in_conditional.compile()
    headers = _discover_loop_headers(compiled)

    from hugr import Node, ops

    hugr = compiled.modules[0]
    tailloop_header = next(h for h in headers if isinstance(hugr[Node(h)].op, ops.TailLoop))
    trip_counts = {h: (5 if h == tailloop_header else 1) for h in headers}

    gate_counts, n_qubits = extract_gate_counts(compiled, upper_bound=True, loop_trip_counts=trip_counts)

    # Entry: h(ctrl) [1 clifford] + measure(ctrl) [1 measurement], ctrl's
    # own QAlloc [1 qubit]. Then-branch: x(qs[0]) [1 clifford], 3 qubits.
    # Else-branch: no gates, 5 qubits (TailLoop, trip=5).
    # Conditional = elementwise max(then, else) = (clifford:1, n_qubits:5).
    # Total = entry + conditional_max.
    assert gate_counts.clifford == 1 + 1  # entry's h(ctrl) + then-branch's x(qs[0]), via max
    assert gate_counts.measurement == 1
    assert n_qubits == 1 + 5  # ctrl (1) + max(3, 5)


# --- Explicitly unsupported: no known way to construct a differently-
# shaped TailLoop from real guppy source was found in this pass (see
# CLAUDE.md "TailLoop support"), so unlike test_bounded_control_flow.py's
# analogous "unsupported shape" tests, there is no repro to assert against
# here -- documented as an honest gap rather than a fabricated test.