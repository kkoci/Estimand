"""Tests for guppy_estimand's call-following: extract_gate_counts (both
upper_bound=False and upper_bound=True) now recurses into a called
function's own body, using the same traversal that walks the caller,
instead of the old blanket CallNotSupported. See CLAUDE.md
"Call-following" for the full HUGR-verification writeup this is built
against (how ops.Call resolves to its FuncDefn target, why the same
instantiation called from multiple sites shares one FuncDefn node, the
loop_trip_counts composition rules, and the qshelf QFT re-run).
"""

import re

import pytest
from guppylang import guppy
from guppylang.std.builtins import array
from guppylang.std.quantum import discard, h, qubit, x
from guppylang.std.quantum import discard_array

from guppy_estimand.gate_counts import (
    CallNotSupported,
    ControlFlowNotSupported,
    LoopTripCountMissing,
    RecursiveCallNotSupported,
    extract_gate_counts,
)


def _discover_loop_headers(compiled) -> list[int]:
    """Test helper (same pattern as tests/test_bounded_control_flow.py):
    repeatedly calls extract_gate_counts with an ever-growing
    loop_trip_counts dict (placeholder count of 3 each time), recording
    each header LoopTripCountMissing names, until it stops raising.
    Returns headers in discovery order."""
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
            found[header] = 3
    raise AssertionError("did not converge on all loop headers")


# --- Basic call-following: a real, reliably-non-inlined stdlib call ---


def test_call_to_discard_array_is_followed_not_refused():
    """discard_array is reliably compiled as a separate FuncDefn with its
    own internal loop (verified by hand -- see CLAUDE.md), reached via a
    Call node. This must now be followed and counted, not refused."""

    @guppy
    def circ() -> None:
        qs = array(qubit(), qubit())
        h(qs[0])
        discard_array(qs)

    compiled = circ.compile()
    headers = _discover_loop_headers(compiled)
    assert len(headers) == 1  # discard_array's own internal loop
    (header,) = headers

    gate_counts, n_qubits = extract_gate_counts(
        compiled, upper_bound=True, loop_trip_counts={header: 2}
    )
    # Only the visible h(qs[0]) contributes a gate; discard_array's own
    # only quantum op is QFree, which is in _IGNORED (contributes 0).
    assert gate_counts.clifford == 1
    assert n_qubits == 2




# --- Step 3: same callee, called from different contexts ---
#
# A helper large enough to survive guppylang's inlining threshold (plain,
# non-generic helpers were found by hand to get inlined up to at least 32
# gates across 2 call sites -- see CLAUDE.md "Call-following" -- but NOT at
# 100 gates single-call-site; confirmed empirically, not guessed). 50
# repetitions of (h, x) below = 100 clifford gates per call.


@guppy
def _big_helper(q: qubit) -> None:
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)
    h(q)
    x(q)


def test_same_callee_called_outside_and_inside_a_loop():
    """The core test the task asked for: the SAME function called once
    outside a loop and once inside a loop with trip count N. Gate counts
    must reflect each call site's own context (1x for the outside call,
    Nx for the inside call), NOT a single memoized count applied
    everywhere (which would give 2x, ignoring N) and not just 1x (which
    would silently drop the loop multiplication for the second call)."""

    @guppy
    def main() -> None:
        q0 = qubit()
        q1 = qubit()
        _big_helper(q0)  # call site 1: outside any loop -> 1x
        i = 0
        while i < 3:
            _big_helper(q1)  # call site 2: inside a loop -> Nx
            i += 1
        discard(q0)
        discard(q1)

    compiled = main.compile()
    headers = _discover_loop_headers(compiled)
    assert len(headers) == 1  # main's own while loop (_big_helper itself is straight-line)
    (header,) = headers

    for trip_count in (3, 0, 7):
        gate_counts, n_qubits = extract_gate_counts(
            compiled, upper_bound=True, loop_trip_counts={header: trip_count}
        )
        expected = 100 * (1 + trip_count)
        assert gate_counts.clifford == expected
        assert n_qubits == 2


def test_same_callee_memoized_not_recomputed_but_recounted_per_site():
    """Complementary check: calling the SAME callee from THREE separate
    call sites, all outside any loop, must give 3x -- confirming
    memoization (avoiding re-walking the callee's body) does not
    accidentally become de-duplication (undercounting how many times its
    cost is added)."""

    @guppy
    def main() -> None:
        q0 = qubit()
        _big_helper(q0)
        _big_helper(q0)
        _big_helper(q0)
        discard(q0)

    compiled = main.compile()
    gate_counts, n_qubits = extract_gate_counts(compiled, upper_bound=True, loop_trip_counts={})
    assert gate_counts.clifford == 300
    assert n_qubits == 1


# --- Step 4: recursion is detected and refused loudly, not looped/guessed ---
#
# guppylang does allow writing a genuinely recursive function (verified by
# hand -- see CLAUDE.md); a recursive function cannot be inlined by
# construction (there is no finite inlining depth), so it reliably produces
# a real Call node pointing back to its own FuncDefn, giving a clean,
# fully-controlled test case (unlike the inlining-threshold guesswork
# needed for the non-recursive repeated-call tests above).


@guppy
def _rec(q: qubit, n: int) -> None:
    h(q)
    if n > 0:
        _rec(q, n - 1)


def test_direct_recursion_detected_in_bounded_mode():
    @guppy
    def main() -> None:
        q = qubit()
        _rec(q, 3)
        discard(q)

    compiled = main.compile()
    with pytest.raises(RecursiveCallNotSupported, match=r"HUGR node Node\(\d+\)"):
        extract_gate_counts(compiled, upper_bound=True, loop_trip_counts={})


def test_direct_recursion_in_straight_line_mode_fails_loudly_one_way_or_another():
    """`_rec`'s own base-case check (`if n > 0`) is itself a HUGR CFG, so
    straight-line mode (which does not bound conditionals at all) hits
    ControlFlowNotSupported on THAT before ever reaching the recursive
    Call node -- a legitimate, different-but-still-loud failure route.
    This is not a coincidence special to this example: any practical
    recursive function needs a base case to terminate, which is expressed
    as a conditional/branch, so in practice straight-line mode is expected
    to always hit ControlFlowNotSupported before RecursiveCallNotSupported
    for real recursive guppy code -- documented explicitly rather than
    quietly assumed. The recursion-cycle-detection code path (shared via
    _walk_call with bounded mode) still exists and is exercised directly
    by the bounded-mode test above; this test only confirms straight-line
    mode does not silently succeed or hang instead."""

    @guppy
    def main() -> None:
        q = qubit()
        _rec(q, 3)
        discard(q)

    compiled = main.compile()
    with pytest.raises((ControlFlowNotSupported, RecursiveCallNotSupported)):
        extract_gate_counts(compiled)


def test_indirect_mutual_recursion_detected():
    """A calls B calls A -- indirect recursion, not just direct self-calls.
    Uses the same call_stack-based cycle detection (any FuncDefn already
    on the current walk's call stack is a cycle, regardless of how many
    intermediate functions are on the path)."""

    @guppy
    def mutual_b(q: qubit, n: int) -> None:
        h(q)
        if n > 0:
            mutual_a(q, n - 1)

    @guppy
    def mutual_a(q: qubit, n: int) -> None:
        h(q)
        if n > 0:
            mutual_b(q, n - 1)

    @guppy
    def main() -> None:
        q = qubit()
        mutual_a(q, 3)
        discard(q)

    compiled = main.compile()
    with pytest.raises(RecursiveCallNotSupported):
        extract_gate_counts(compiled, upper_bound=True, loop_trip_counts={})


# --- Opaque calls: CallNotSupported narrowed, not removed ---


def test_call_not_supported_still_importable_for_opaque_calls():
    """CallNotSupported is narrowed (2026-09-05), not deleted: it still
    exists for calls this project genuinely cannot resolve to a walkable
    body (CallIndirect, or a Call targeting a FuncDecl) -- see the class
    docstring. No guppy source pattern found in this project's testing
    reliably produces either shape (guppylang's compiler was not observed
    to emit CallIndirect or FuncDecl-backed calls for any pattern tried),
    so this is a smoke test that the exception class and its narrowed
    docstring are in place, not a HUGR-level repro of triggering it --
    documented as an honest gap rather than a fabricated test."""
    assert issubclass(CallNotSupported, NotImplementedError)
    assert "CallIndirect" in CallNotSupported.__doc__
    assert "FuncDecl" in CallNotSupported.__doc__

