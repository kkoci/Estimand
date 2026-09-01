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


# --- Part 5: nested loops ---
#
# A while loop nested inside another while loop was NOT covered by the
# loop-in-conditional / conditional-in-loop composition tests above, and
# turned out to expose a real bug (RecursionError): the CFG-block DP's
# restricted "one pass through an outer loop's body" walk (`dp_within` in
# gate_counts.py) did not recognize a nested loop header as anything other
# than an ordinary branch point, so it never stopped at the inner loop's
# own back edge. Fixed in gate_counts.py by making `dp_within` recognize
# and fully unroll a nested header (its own trip count, its own body walk)
# before continuing past it -- see the docstring on `dp_within` there, and
# CLAUDE.md "HUGR quirks" (2026-09-03) for the hand-verified HUGR structure
# (still ONE CFG, two back edges, inner loop's node set entirely absorbed
# into the outer loop's natural-loop node set).


def _discover_loop_headers(compiled) -> list[int]:
    """Test helper: repeatedly calls extract_gate_counts with an
    ever-growing loop_trip_counts dict (placeholder count of 1 each time),
    recording each header LoopTripCountMissing names, until it stops
    raising. Returns headers in DISCOVERY order -- which, given dp() checks
    an outer header before recursing into its body via dp_within, means
    outer loops are discovered before loops nested inside them."""
    found: dict[int, int] = {}
    order: list[int] = []
    for _ in range(20):
        try:
            extract_gate_counts(compiled, upper_bound=True, loop_trip_counts=found)
            return order
        except LoopTripCountMissing as e:
            import re

            m = re.search(r"HUGR node (\d+)", str(e))
            assert m, str(e)
            header = int(m.group(1))
            order.append(header)
            found[header] = 1
    raise AssertionError("did not converge on all loop headers")


def _nested_while_loops_circ():
    @guppy
    def circ() -> None:
        q0 = qubit()
        i = 0
        while i < 3:
            j = 0
            while j < 2:
                h(q0)  # inner body: should scale by outer_trip * inner_trip
                j += 1
            i += 1
        discard(q0)

    return circ


def test_nested_loop_no_longer_crashes_and_scales_inner_body_by_product():
    """Regression test for the RecursionError bug described above. Inner
    loop body gates must scale by outer_trip * inner_trip, checked across
    several (M, N) pairs including zeros -- not M+N, not just M, not just N."""
    compiled = _nested_while_loops_circ().compile()
    headers = _discover_loop_headers(compiled)
    assert len(headers) == 2
    outer, inner = headers  # outer discovered first, see _discover_loop_headers

    for outer_trip, inner_trip in [(3, 2), (5, 1), (1, 7), (0, 5), (4, 0)]:
        gate_counts, n_qubits = extract_gate_counts(
            compiled,
            upper_bound=True,
            loop_trip_counts={outer: outer_trip, inner: inner_trip},
        )
        assert gate_counts.clifford == outer_trip * inner_trip
        # QAlloc is outside both loops (before the outer `while`) -- never
        # scaled by either trip count.
        assert n_qubits == 1


def test_nested_loop_outer_only_gates_scale_by_outer_trip_alone():
    """A gate in the outer loop's body but OUTSIDE the inner loop must
    scale by outer_trip only; a gate inside the inner loop must scale by
    outer_trip * inner_trip -- in the SAME program, so a bug that collapses
    the two distinctions (e.g. scaling everything in the outer body by
    outer_trip*inner_trip, or by outer_trip+inner_trip) is caught."""

    @guppy
    def circ() -> None:
        q0 = qubit()
        i = 0
        while i < 3:
            x(q0)  # outer-body-only: scales by outer_trip alone
            j = 0
            while j < 2:
                h(q0)  # inner body: scales by outer_trip * inner_trip
                j += 1
            i += 1
        discard(q0)

    compiled = circ.compile()
    headers = _discover_loop_headers(compiled)
    assert len(headers) == 2
    outer, inner = headers

    for outer_trip, inner_trip in [(3, 2), (5, 1), (2, 4)]:
        gate_counts, _ = extract_gate_counts(
            compiled,
            upper_bound=True,
            loop_trip_counts={outer: outer_trip, inner: inner_trip},
        )
        # x(q0) contributes outer_trip clifford; h(q0) contributes
        # outer_trip*inner_trip clifford; both are the "clifford" bucket.
        expected = outer_trip * (1 + inner_trip)
        assert gate_counts.clifford == expected


def test_nested_loop_qubit_allocated_in_inner_body_not_scaled_by_either_trip():
    """A qubit allocated (and freed) fresh each INNERMOST iteration must
    still count once, not outer_trip*inner_trip times -- the single-loop
    n_qubits reasoning (guppy's linear qubit typing forces free-within-one-
    iteration, so the same physical slot is reused) extends unchanged to
    nested loops: _scale_gates_only leaves n_qubits untouched at every
    nesting level, including the new nested-header branch in dp_within."""

    @guppy
    def circ() -> None:
        i = 0
        while i < 3:
            j = 0
            while j < 2:
                q = qubit()
                h(q)
                discard(q)
                j += 1
            i += 1

    compiled = circ.compile()
    headers = _discover_loop_headers(compiled)
    assert len(headers) == 2
    outer, inner = headers

    gate_counts, n_qubits = extract_gate_counts(
        compiled, upper_bound=True, loop_trip_counts={outer: 3, inner: 2}
    )
    assert gate_counts.clifford == 6  # 3 * 2
    assert n_qubits == 1  # NOT 6


def test_nested_loop_missing_trip_count_names_whichever_header_is_missing():
    """LoopTripCountMissing must name the actual missing header, whether
    that's the outer loop (nothing supplied yet) or specifically the inner
    loop (outer supplied, inner still missing) -- not always report the
    outermost header regardless of which one is actually absent."""
    compiled = _nested_while_loops_circ().compile()
    headers = _discover_loop_headers(compiled)
    outer, inner = headers

    # Nothing supplied: outer is reported first (dp() checks its own
    # header before recursing into dp_within for the body).
    with pytest.raises(LoopTripCountMissing, match=rf"HUGR node {outer}\b"):
        extract_gate_counts(compiled, upper_bound=True, loop_trip_counts={})

    # Outer supplied, inner missing: the INNER header must be named, not
    # the outer one again and not a generic/wrong message.
    with pytest.raises(LoopTripCountMissing, match=rf"HUGR node {inner}\b"):
        extract_gate_counts(compiled, upper_bound=True, loop_trip_counts={outer: 3})


def test_nested_loop_composes_with_conditional_in_inner_body():
    """A conditional inside the inner loop's body: the heavier branch's
    gates should scale by outer_trip * inner_trip, same as any other
    inner-loop-body gate -- checks the fix composes with the pre-existing
    (already-tested) conditional max-of-branches logic, not just loops
    alone."""

    @guppy
    def circ() -> None:
        q0 = qubit()
        ctrl = qubit()
        h(ctrl)
        b = measure(ctrl)
        i = 0
        while i < 3:
            j = 0
            while j < 2:
                if b:
                    h(q0)
                else:
                    h(q0)
                    x(q0)  # heavier branch: 2 clifford
                j += 1
            i += 1
        discard(q0)

    compiled = circ.compile()
    headers = _discover_loop_headers(compiled)
    outer, inner = headers
    outer_trip, inner_trip = 3, 2

    gate_counts, _ = extract_gate_counts(
        compiled,
        upper_bound=True,
        loop_trip_counts={outer: outer_trip, inner: inner_trip},
    )
    # Entry (h(ctrl), 1 clifford) + outer_trip*inner_trip * max(1, 2).
    expected = 1 + outer_trip * inner_trip * 2
    assert gate_counts.clifford == expected
