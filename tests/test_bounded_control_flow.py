"""Tests for guppy_estimand's opt-in upper_bound / loop_trip_counts mode.

See CLAUDE.md "HUGR quirks" (2026-09-02) for the hand-verified HUGR
structures these tests are built against, and "Bounded control flow
(opt-in)" for the documented design (why loops are keyed by HUGR node ID,
why n_qubits is not scaled by trip count, why TailLoop and `for`-over-an-
iterator are explicitly unsupported).
"""

import pytest
from guppylang import guppy
from guppylang.std.quantum import cx, discard, h, measure, qubit, x

from guppy_estimand.gate_counts import (
    LoopTripCountMissing,
    UnsupportedControlFlowShape,
    extract_gate_counts,
)


# --- Part 1: conditional upper bound ---


def _asymmetric_branches_circ():
    @guppy
    def circ() -> None:
        q0 = qubit()
        q1 = qubit()
        ctrl = qubit()
        h(ctrl)
        b = measure(ctrl)
        if b:
            h(q0)  # then: 1 clifford
        else:
            h(q0)
            cx(q0, q1)  # else: 2 clifford -- heavier branch
        discard(q0)
        discard(q1)

    return circ


def test_single_conditional_upper_bound_matches_heavier_branch():
    circ = _asymmetric_branches_circ()
    gate_counts, n_qubits = extract_gate_counts(circ.compile(), upper_bound=True)

    # Entry block (h(ctrl), 1 clifford; measure(ctrl), 1 measurement) always
    # runs, then the heavier ("else") branch (2 clifford) should be the one
    # reflected: 1 + 2 = 3 total clifford -- NOT 1+1=2 (lighter branch) and
    # NOT 1+1+2=4 (sum of both branches).
    assert gate_counts.clifford == 3
    assert gate_counts.measurement == 1
    assert n_qubits == 3


def test_conditional_without_upper_bound_still_raises():
    """The default path is unchanged: upper_bound defaults to False."""
    circ = _asymmetric_branches_circ()
    from guppy_estimand.gate_counts import ControlFlowNotSupported

    with pytest.raises(ControlFlowNotSupported):
        extract_gate_counts(circ.compile())


def test_sequential_independent_conditionals_sum_of_max_per_conditional():
    """Two independent, sequential if/else blocks in one function compile
    to a SINGLE CFG containing both conditionals' DataflowBlocks as
    siblings (verified by hand -- see CLAUDE.md). The correct upper bound
    is sum-of-max-branch-PER-conditional, not max-of-all-four-branches and
    not sum-of-all-four-branches-treated-as-one-set. This test is
    specifically designed so those three answers are all different, so
    getting the grouping wrong is caught."""

    @guppy
    def circ() -> None:
        q0 = qubit()
        q1 = qubit()
        ctrl1 = qubit()
        ctrl2 = qubit()
        h(ctrl1)
        h(ctrl2)
        b1 = measure(ctrl1)
        b2 = measure(ctrl2)
        if b1:
            h(q0)  # conditional 1, then: 1 clifford
        else:
            h(q0)
            cx(q0, q1)  # conditional 1, else: 2 clifford (heavier)
        if b2:
            h(q1)
            cx(q1, q0)
            cx(q0, q1)  # conditional 2, then: 3 clifford (heavier)
        else:
            x(q1)  # conditional 2, else: 1 clifford
        discard(q0)
        discard(q1)

    gate_counts, n_qubits = extract_gate_counts(circ.compile(), upper_bound=True)

    # Entry block: h(ctrl1), h(ctrl2) -> 2 clifford, always runs.
    # Correct answer: 2 (entry) + 2 (max of conditional 1's branches) +
    # 3 (max of conditional 2's branches) = 7.
    # Sum-of-all-four-branches-as-one-set (wrong): 2 + (1+2) + (3+1) = 9.
    # Max-of-all-four-branches-ignoring-grouping (wrong): 2 + max(1,2,3,1) = 5.
    assert gate_counts.clifford == 7
    assert n_qubits == 4


# --- Part 2: loop trip counts ---


def _simple_while_loop_circ():
    @guppy
    def circ() -> None:
        q0 = qubit()
        i = 0
        while i < 3:
            h(q0)
            i += 1
        discard(q0)

    return circ


def _find_loop_header(hugr):
    """Test helper: find the single loop header's node id by re-running the
    same back-edge detection the walker uses, via the public API's error
    message (LoopTripCountMissing names the header's node id explicitly)."""
    from guppy_estimand.gate_counts import extract_gate_counts as _egc

    try:
        _egc(hugr, upper_bound=True, loop_trip_counts={})
    except LoopTripCountMissing as e:
        import re

        m = re.search(r"HUGR node (\d+)", str(e))
        assert m, str(e)
        return int(m.group(1))
    raise AssertionError("expected LoopTripCountMissing")


def test_loop_without_trip_count_raises_naming_the_header():
    circ = _simple_while_loop_circ()
    compiled = circ.compile()
    with pytest.raises(LoopTripCountMissing, match=r"HUGR node \d+"):
        extract_gate_counts(compiled, upper_bound=True)


def test_loop_trip_count_multiplies_body_gates_not_qubits():
    circ = _simple_while_loop_circ()
    compiled = circ.compile()
    header = _find_loop_header(compiled)

    gate_counts, n_qubits = extract_gate_counts(
        compiled, upper_bound=True, loop_trip_counts={header: 5}
    )

    # Body is h(q0) -> 1 clifford per iteration, run 5 times = 5 clifford.
    assert gate_counts.clifford == 5
    # QAlloc happens once, statically, before the loop -- not multiplied.
    assert n_qubits == 1


def test_loop_trip_count_zero_means_body_never_runs():
    circ = _simple_while_loop_circ()
    compiled = circ.compile()
    header = _find_loop_header(compiled)

    gate_counts, n_qubits = extract_gate_counts(
        compiled, upper_bound=True, loop_trip_counts={header: 0}
    )
    assert gate_counts.clifford == 0
    assert n_qubits == 1


def test_two_independent_loops_keyed_by_distinct_node_ids():
    @guppy
    def circ() -> None:
        q0 = qubit()
        q1 = qubit()
        i = 0
        while i < 3:
            h(q0)
            i += 1
        j = 0
        while j < 3:
            x(q1)
            j += 1
        discard(q0)
        discard(q1)

    compiled = circ.compile()

    # Discover both headers by trying with an empty dict, then a dict with
    # only the first found, etc. Simpler: just try increasing supplied sets
    # until it succeeds, recording each missing header along the way.
    from guppy_estimand.gate_counts import extract_gate_counts as _egc

    found = {}
    for _ in range(10):
        try:
            _egc(compiled, upper_bound=True, loop_trip_counts=found)
            break
        except LoopTripCountMissing as e:
            import re

            m = re.search(r"HUGR node (\d+)", str(e))
            assert m, str(e)
            found[int(m.group(1))] = 1  # placeholder trip count while discovering
    else:
        raise AssertionError("did not converge on all loop headers")

    assert len(found) == 2
    h1, h2 = sorted(found)

    gate_counts, n_qubits = extract_gate_counts(
        compiled, upper_bound=True, loop_trip_counts={h1: 4, h2: 7}
    )
    # One loop's body is h(q0) (clifford), the other's is x(q1) (clifford
    # too) -- both count as clifford, so total clifford = 4 + 7 = 11,
    # regardless of which node id belongs to which loop (order-independent
    # by construction of this test, since both bodies are single-clifford-op).
    assert gate_counts.clifford == 11
    assert n_qubits == 2

    # Supplying only one of the two required counts still raises, naming
    # the OTHER (still-missing) header -- not silently defaulting it.
    with pytest.raises(LoopTripCountMissing):
        extract_gate_counts(compiled, upper_bound=True, loop_trip_counts={h1: 4})


# --- Part 3: composition ---


def test_loop_containing_a_conditional():
    @guppy
    def circ() -> None:
        q0 = qubit()
        ctrl = qubit()
        h(ctrl)
        b = measure(ctrl)
        i = 0
        while i < 3:
            if b:
                h(q0)  # then: 1 clifford
            else:
                x(q0)
                h(q0)  # else: 2 clifford -- heavier
            i += 1
        discard(q0)

    compiled = circ.compile()
    header = _find_loop_header(compiled)

    gate_counts, n_qubits = extract_gate_counts(
        compiled, upper_bound=True, loop_trip_counts={header: 4}
    )

    # Entry (h(ctrl), 1 clifford) + 4 * max(1, 2) = 1 + 8 = 9.
    assert gate_counts.clifford == 9
    assert n_qubits == 2


def test_conditional_containing_a_loop():
    @guppy
    def circ() -> None:
        q0 = qubit()
        ctrl = qubit()
        h(ctrl)
        b = measure(ctrl)
        if b:
            i = 0
            while i < 3:
                h(q0)  # loop body: 1 clifford per iteration
                i += 1
        else:
            # NOT x(q0) three times in a row: guppy's default compile()
            # optimization pass cancels repeated-identical adjacent gates
            # (verified by hand -- 3x consecutive X folds to 1x X in the
            # HUGR; see CLAUDE.md "HUGR quirks"). Use distinct gate types
            # instead so all 3 survive as separate ops.
            h(q0)
            x(q0)
            h(q0)  # else branch: 3 clifford, no loop
        discard(q0)

    compiled = circ.compile()
    header = _find_loop_header(compiled)

    # With a high trip count, the "then" branch (containing the loop)
    # should dominate the max.
    gate_counts, n_qubits = extract_gate_counts(
        compiled, upper_bound=True, loop_trip_counts={header: 10}
    )
    # Entry (h(ctrl), 1 clifford) + max(10 * 1, 3) = 1 + 10 = 11.
    assert gate_counts.clifford == 11
    assert n_qubits == 2

    # With a low trip count, the "else" branch (no loop) should dominate.
    gate_counts_low, _ = extract_gate_counts(
        compiled, upper_bound=True, loop_trip_counts={header: 1}
    )
    # Entry (1) + max(1 * 1, 3) = 1 + 3 = 4.
    assert gate_counts_low.clifford == 4


# --- Part 4: explicitly unsupported shapes fail loudly, not silently ---


def test_for_loop_over_range_is_unsupported():
    """for-over-range compiles to a nested CFG plus iterator-protocol
    Option/panic machinery (verified by hand -- see CLAUDE.md), which is
    NOT the single-CFG-with-back-edge shape this module supports. It must
    fail loudly (UnsupportedControlFlowShape or LoopTripCountMissing),
    never silently produce a number."""

    @guppy
    def circ() -> None:
        q0 = qubit()
        for _ in range(3):
            h(q0)
        discard(q0)

    compiled = circ.compile()
    with pytest.raises((UnsupportedControlFlowShape, LoopTripCountMissing)):
        extract_gate_counts(compiled, upper_bound=True, loop_trip_counts={})
