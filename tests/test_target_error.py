"""Tests for guppy_estimand's target_error auto-selection of data_d (added
2026-09-08). See CLAUDE.md "Auto-selecting data_d" for the full derivation:
model.error() was verified BY HAND (not assumed) to be monotonically
non-increasing in data_d, with a real floor set by the magic-state
factory's own data_d-independent error contribution -- which is why
bisection is valid, and why a sufficiently strict target_error must fail
loudly rather than return a distance that doesn't actually work.
"""

import pytest
from guppylang import guppy
from guppylang.std.quantum import cx, h, measure, qubit, t

from guppy_estimand import estimate
from guppy_estimand.estimate import _build_model


@guppy
def bell_and_t() -> None:
    q0 = qubit()
    q1 = qubit()
    h(q0)
    cx(q0, q1)
    t(q0)
    measure(q0)
    measure(q1)


# --- Mutual exclusivity ---


def test_neither_data_d_nor_target_error_raises():
    with pytest.raises(ValueError, match="neither"):
        estimate(bell_and_t.compile())


def test_both_data_d_and_target_error_raises():
    with pytest.raises(ValueError, match="both"):
        estimate(bell_and_t.compile(), data_d=17, target_error=1e-6)


def test_target_error_must_be_positive():
    with pytest.raises(ValueError, match="positive"):
        estimate(bell_and_t.compile(), target_error=0.0)
    with pytest.raises(ValueError, match="positive"):
        estimate(bell_and_t.compile(), target_error=-1e-6)


# For `bell_and_t` specifically, the achievable-error floor (the magic
# state factory's own, data_d-independent error contribution -- see the
# module docstring) differs by scheme: beverland's floor is ~2.033e-05,
# gidney_fowler's is ~5.333e-11 (checked by hand, not guessed -- see
# CLAUDE.md "Auto-selecting data_d"). Target-error lists below are chosen
# comfortably above each scheme's own floor so they're genuinely
# achievable; the *unachievable* case is exercised separately below.
_ACHIEVABLE_TARGETS = [
    ("beverland", 1e-2),
    ("beverland", 1e-3),
    ("beverland", 1e-4),
    ("gidney_fowler", 1e-2),
    ("gidney_fowler", 1e-4),
    ("gidney_fowler", 1e-6),
    ("gidney_fowler", 1e-8),
]


# --- Basic correctness: achieves the budget, is odd, is >= 3 ---


@pytest.mark.parametrize(("scheme", "target_error"), _ACHIEVABLE_TARGETS)
def test_target_error_achieves_the_budget(scheme, target_error):
    result = estimate(bell_and_t.compile(), scheme=scheme, target_error=target_error)
    assert result.error <= target_error
    assert result.data_d >= 3
    assert result.data_d % 2 == 1


# --- Smallest such distance, not just "a" distance that works ---


@pytest.mark.parametrize(("scheme", "target_error"), _ACHIEVABLE_TARGETS)
def test_target_error_selects_the_smallest_achieving_distance(scheme, target_error):
    """A larger data_d always costs more physical qubits (2*d^2 per tile),
    so returning a distance looser than necessary would silently make
    guppy_estimand's own output more expensive than it needs to be. Checks
    the returned d actually achieves the target AND that d-2 (the next
    smaller odd distance) does not -- confirming this is the smallest, not
    merely a sufficient, distance. Skips the check at d=3 (the search
    floor -- there's no smaller odd distance to compare against)."""
    from guppy_estimand.gate_counts import extract_gate_counts
    from qualtran.surface_code import AlgorithmSummary

    result = estimate(bell_and_t.compile(), scheme=scheme, target_error=target_error)
    assert result.error <= target_error

    if result.data_d == 3:
        return  # smallest possible distance; nothing smaller to compare against

    gate_counts, n_qubits = extract_gate_counts(bell_and_t.compile())
    algo_summary = AlgorithmSummary(n_algo_qubits=n_qubits, n_logical_gates=gate_counts)
    smaller_error = _build_model(scheme, result.data_d - 2).error(algo_summary)
    assert smaller_error > target_error, (
        f"data_d={result.data_d - 2} already achieves target_error={target_error:.3e} "
        f"(error={smaller_error:.3e}) -- estimate() returned a larger d={result.data_d} "
        "than necessary"
    )


# --- Consistency with the fixed-data_d path: same numbers either way ---


@pytest.mark.parametrize(("scheme", "target_error"), [("beverland", 1e-4), ("gidney_fowler", 1e-8)])
def test_target_error_result_matches_fixed_data_d_result(scheme, target_error):
    """Auto-selection must not be a parallel code path with its own
    numbers -- once it picks a d, re-running estimate() with that exact
    data_d must give an identical EstimateResult (n_phys_qubits,
    duration_hr, error), confirming _select_data_d_for_target_error feeds
    into the same _build_model()/EstimateResult construction as the
    ordinary data_d= call, not a separate computation."""
    auto = estimate(bell_and_t.compile(), scheme=scheme, target_error=target_error)
    fixed = estimate(bell_and_t.compile(), scheme=scheme, data_d=auto.data_d)

    assert auto.n_phys_qubits == fixed.n_phys_qubits
    assert auto.duration_hr == fixed.duration_hr
    assert auto.error == fixed.error


# --- Trivially loose target: returns the search floor, not d=1 ---


@pytest.mark.parametrize("scheme", ["beverland", "gidney_fowler"])
def test_extremely_loose_target_error_returns_minimum_search_distance(scheme):
    """A target so loose that even the smallest searched distance (d=3)
    already achieves it should return d=3 immediately -- not d=1 (excluded
    by design; a distance-1 surface code corrects zero errors -- see
    CLAUDE.md), and not some other distance found via unnecessary search."""
    result = estimate(bell_and_t.compile(), scheme=scheme, target_error=1e10)
    assert result.data_d == 3


# --- Unachievable target: fails loudly with diagnostics, doesn't silently
# return the search cap as if it were a real answer ---


@pytest.mark.parametrize("scheme", ["beverland", "gidney_fowler"])
def test_unachievable_target_error_raises_with_achieved_error_shown(scheme):
    """Below the magic-state factory's own error floor (independent of
    data_d -- see module docstring), NO data_d can ever achieve the
    target. Must raise loudly, naming the achieved error at the search
    boundary, rather than silently returning the largest distance tried
    (which would still not actually achieve target_error) or some other
    wrong-but-plausible-looking distance."""
    with pytest.raises(ValueError, match=r"No code distance up to d=\d+ achieves") as exc_info:
        estimate(bell_and_t.compile(), scheme=scheme, target_error=1e-300)
    message = str(exc_info.value)
    assert "achieved error=" in message


# --- Real-world example: bisected against the hand-verified Grover gate profile ---


def test_target_error_against_real_grover_example():
    """Uses the real, hand-verified Grover gate counts from this project's
    CallIndirect-support pass (toffoli=4, clifford=47, n_qubits=3 -- see
    CLAUDE.md "CallIndirect support") rather than a synthetic profile, to
    confirm auto-selection composes correctly with a genuine multi-gate-
    type real-world result, not just the 1-2-gate bell_and_t toy."""
    from examples._qshelf_grover import grover_search, optimal_iterations  # noqa: PLC0415
    from guppylang.std.builtins import array
    from guppylang.std.quantum import discard_array
    from guppy_estimand.gate_counts import LoopTripCountMissing, extract_gate_counts
    import re

    marked = 5
    iterations = optimal_iterations(8, 1)

    @guppy
    def circ() -> None:
        qs = array(qubit() for _ in range(3))
        grover_search[marked, iterations](qs)
        discard_array(qs)

    compiled = circ.compile()
    found: dict[int, int] = {}
    headers: list[int] = []
    for _ in range(30):
        try:
            extract_gate_counts(compiled, upper_bound=True, loop_trip_counts=found)
            break
        except LoopTripCountMissing as e:
            m = re.search(r"HUGR node (\d+)", str(e))
            header = int(m.group(1))
            headers.append(header)
            found[header] = 3
    iterations_header = None
    for candidate in headers:
        trial = {h: (50 if h == candidate else 3) for h in headers}
        gc, _ = extract_gate_counts(compiled, upper_bound=True, loop_trip_counts=trial)
        if gc.toffoli > 10:
            iterations_header = candidate
            break
    trip_counts = {h: (iterations if h == iterations_header else 3) for h in headers}

    # Grover's toffoli-heavy gate profile pushes the magic-state factory's
    # own error contribution higher than bell_and_t's -- its beverland
    # floor is ~3.253e-04 (checked by hand), so 1e-3 (not 1e-4) is the
    # comfortably-achievable target used here.
    target_error = 1e-3
    result = estimate(
        compiled,
        scheme="beverland",
        target_error=target_error,
        upper_bound=True,
        loop_trip_counts=trip_counts,
    )
    assert result.gate_counts.toffoli == 4
    assert result.gate_counts.clifford == 47
    assert result.error <= target_error
    assert result.data_d >= 3 and result.data_d % 2 == 1
