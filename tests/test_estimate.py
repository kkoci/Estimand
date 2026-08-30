from guppylang import guppy
from guppylang.std.quantum import cx, h, measure, qubit, t
from qualtran.resource_counting import GateCounts
from qualtran.surface_code import AlgorithmSummary, PhysicalCostModel

from guppy_estimand import estimate


@guppy
def bell_and_t() -> None:
    q0 = qubit()
    q1 = qubit()
    h(q0)
    cx(q0, q1)
    t(q0)
    measure(q0)
    measure(q1)


def test_estimate_matches_direct_qualtran_call():
    """The adapter's output must equal calling Qualtran directly on the same
    GateCounts -- this is the plumbing this project owns; the surface-code
    math itself is Qualtran's (see CLAUDE.md citations)."""
    result = estimate(bell_and_t.compile(), scheme="beverland", data_d=17)

    expected_gate_counts = GateCounts(t=1, clifford=2, measurement=2)
    expected_summary = AlgorithmSummary(n_algo_qubits=2, n_logical_gates=expected_gate_counts)
    expected_model = PhysicalCostModel.make_beverland_et_al(data_d=17)

    assert result.gate_counts == expected_gate_counts
    assert result.n_algo_qubits == 2
    assert result.n_phys_qubits == expected_model.n_phys_qubits(expected_summary)
    assert result.duration_hr == expected_model.duration_hr(expected_summary)
    assert result.error == expected_model.error(expected_summary)


def test_gidney_fowler_scheme_runs():
    result = estimate(bell_and_t.compile(), scheme="gidney_fowler", data_d=17)
    assert result.n_phys_qubits > 0
    assert result.duration_hr > 0
    assert result.error > 0
