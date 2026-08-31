from guppylang import guppy
from guppylang.std.quantum import cx, h, measure, qubit, t
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
