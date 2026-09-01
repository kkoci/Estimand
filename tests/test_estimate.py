import re

import pytest
from guppylang import guppy
from guppylang.std.quantum import cx, discard, h, measure, qubit, t, x
from qualtran.resource_counting import GateCounts
from qualtran.surface_code import (
    AlgorithmSummary,
    FifteenToOne,
    PhysicalCostModel,
    PhysicalParameters,
    QECScheme,
)

from guppy_estimand import estimate
from guppy_estimand._qualtran_patches import CorrectedCompactDataBlock
from guppy_estimand.gate_counts import ControlFlowNotSupported, LoopTripCountMissing


@guppy
def bell_and_t() -> None:
    q0 = qubit()
    q1 = qubit()
    h(q0)
    cx(q0, q1)
    t(q0)
    measure(q0)
    measure(q1)


def test_estimate_matches_locally_corrected_qualtran_model():
    """The adapter's beverland-scheme output must equal building
    PhysicalCostModel by hand with the same locally-corrected
    CompactDataBlock this project uses to fix quantumlib/Qualtran#1943 --
    NOT Qualtran's raw, uncorrected make_beverland_et_al() preset (see
    guppy_estimand._qualtran_patches, CLAUDE.md, VERIFICATION.md Sec. 8)."""
    result = estimate(bell_and_t.compile(), scheme="beverland", data_d=17)

    expected_gate_counts = GateCounts(t=1, clifford=2, measurement=2)
    expected_summary = AlgorithmSummary(n_algo_qubits=2, n_logical_gates=expected_gate_counts)
    expected_model = PhysicalCostModel(
        physical_params=PhysicalParameters.make_beverland_et_al(),
        data_block=CorrectedCompactDataBlock(data_d=17),
        factory=FifteenToOne(9, 3, 3),
        qec_scheme=QECScheme.make_beverland_et_al(),
    )

    assert result.gate_counts == expected_gate_counts
    assert result.n_algo_qubits == 2
    assert result.n_phys_qubits == expected_model.n_phys_qubits(expected_summary)
    assert result.duration_hr == expected_model.duration_hr(expected_summary)
    assert result.error == expected_model.error(expected_summary)


def test_beverland_scheme_intentionally_diverges_from_raw_qualtran():
    """Documents the intentional divergence from calling Qualtran directly:
    this project patches quantumlib/Qualtran#1943 (CompactDataBlock's
    missing "+3" tiles) locally, so estimate()'s n_phys_qubits for the
    default compact data block is NOT equal to
    PhysicalCostModel.make_beverland_et_al().n_phys_qubits() -- it's higher
    by exactly 3 tiles' worth of physical qubits (2*d^2 per tile)."""
    data_d = 17
    result = estimate(bell_and_t.compile(), scheme="beverland", data_d=data_d)

    raw_gate_counts = GateCounts(t=1, clifford=2, measurement=2)
    raw_summary = AlgorithmSummary(n_algo_qubits=2, n_logical_gates=raw_gate_counts)
    raw_model = PhysicalCostModel.make_beverland_et_al(data_d=data_d)

    expected_extra_qubits = 3 * 2 * data_d**2
    assert result.n_phys_qubits == raw_model.n_phys_qubits(raw_summary) + expected_extra_qubits
    assert result.data_block_name == "compact"


def test_gidney_fowler_scheme_runs():
    result = estimate(bell_and_t.compile(), scheme="gidney_fowler", data_d=17)
    assert result.n_phys_qubits > 0
    assert result.duration_hr > 0
    assert result.error > 0
    assert result.data_block_name is None


def test_estimate_upper_bound_end_to_end():
    """estimate(upper_bound=True) on a program with both a conditional and a
    loop: gate_counts is bounded correctly (see
    tests/test_bounded_control_flow.py for the gate-count-level tests this
    relies on), is_upper_bound is set, and __str__ says so explicitly."""

    @guppy
    def circ() -> None:
        q0 = qubit()
        ctrl = qubit()
        h(ctrl)
        b = measure(ctrl)
        i = 0
        while i < 3:
            if b:
                h(q0)
            else:
                x(q0)
            i += 1
        discard(q0)

    compiled = circ.compile()

    # Default (upper_bound=False) is unchanged.
    with pytest.raises(ControlFlowNotSupported):
        estimate(compiled)

    # upper_bound=True without a trip count names the missing loop.
    with pytest.raises(LoopTripCountMissing, match=r"HUGR node \d+"):
        estimate(compiled, upper_bound=True)

    # Discover the header the same way a real caller would: from the error.
    try:
        estimate(compiled, upper_bound=True, loop_trip_counts={})
        header = None
    except LoopTripCountMissing as e:
        header = int(re.search(r"HUGR node (\d+)", str(e)).group(1))
    assert header is not None

    result = estimate(
        compiled, scheme="beverland", data_d=17, upper_bound=True, loop_trip_counts={header: 5}
    )

    assert result.is_upper_bound is True
    # Entry (h(ctrl), 1 clifford) + 5 * max(then=1, else=1) = 1 + 5 = 6.
    assert result.gate_counts.clifford == 6
    assert result.n_algo_qubits == 2
    assert "UPPER BOUND" in str(result)
    assert "upper bound" in str(result)  # the per-field annotations, lowercase
