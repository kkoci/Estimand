"""Tests for CallNotSupported -- guarding against a real, serious bug found
via a real-world stress test (qshelf's QFT, see CLAUDE.md "Real-world
stress test").

Before this was added, neither walker followed ``ops.Call`` edges into a
callee compiled as a separate FuncDefn (rather than inlined at the call
site); the callee's gates were simply invisible, with no error --
`extract_gate_counts` would silently return a near-zero gate count for any
program that called such a function. This is not a synthetic edge case:
guppylang 1.0.2 was found to compile `guppylang.std.quantum.discard_array`
-- used by literally every example in qshelf -- as a separate, called
function rather than inlining it, regardless of array size.
"""

import pytest
from guppylang import guppy
from guppylang.std.builtins import array
from guppylang.std.quantum import discard_array, h, qubit

from guppy_estimand.gate_counts import (
    CallNotSupported,
    UnrecognizedGate,
    extract_gate_counts,
)


def _circ_calling_discard_array():
    @guppy
    def circ() -> None:
        qs = array(qubit(), qubit())
        h(qs[0])
        discard_array(qs)

    return circ


def test_bounded_mode_raises_call_not_supported_naming_the_callee():
    """discard_array is reliably compiled as a separate FuncDefn (verified
    by hand -- see CLAUDE.md), reached via a Call node. Bounded mode skips
    non-tket ops on the way there (array-construction bookkeeping), so it
    cleanly reaches the Call and must raise CallNotSupported, naming the
    callee, rather than silently returning a near-zero gate count."""
    compiled = _circ_calling_discard_array().compile()
    with pytest.raises(CallNotSupported, match="discard_array"):
        extract_gate_counts(compiled, upper_bound=True, loop_trip_counts={})


def test_bounded_mode_does_not_silently_undercount_a_call():
    """Directly guards the original bug: without the fix, this call used
    to return (GateCounts(clifford=1), 1) -- only the visible h(qs[0]),
    with discard_array's own (separately-compiled) body entirely invisible
    and no error raised. Now it must raise, not return a plausible-looking
    but wrong number."""
    compiled = _circ_calling_discard_array().compile()
    with pytest.raises(CallNotSupported):
        extract_gate_counts(compiled, upper_bound=True, loop_trip_counts={})


def test_straight_line_mode_fails_loudly_one_way_or_another():
    """Default (upper_bound=False) mode must also never silently produce a
    wrong number for a call to a non-inlined function. Unlike bounded
    mode, the straight-line walker does not skip non-tket ops, so on this
    particular program it may raise UnrecognizedGate (for the array-
    construction bookkeeping ops encountered before the Call, in HUGR
    traversal order) before ever reaching the Call node -- that is still a
    correct, loud failure, just via a different (also legitimate) route.
    Either way, straight-line mode must not succeed silently here."""
    compiled = _circ_calling_discard_array().compile()
    with pytest.raises((CallNotSupported, UnrecognizedGate)):
        extract_gate_counts(compiled)


def test_call_not_supported_message_names_the_hugr_call_node():
    compiled = _circ_calling_discard_array().compile()
    with pytest.raises(CallNotSupported, match=r"HUGR node Node\(\d+\)"):
        extract_gate_counts(compiled, upper_bound=True, loop_trip_counts={})
