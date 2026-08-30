import pytest
from guppylang import guppy
from guppylang.std.angles import pi
from guppylang.std.quantum import cx, discard, h, measure, qubit, rz, t, toffoli, x

from guppy_estimand.gate_counts import ControlFlowNotSupported, extract_gate_counts


def test_straight_line_gate_counts():
    @guppy
    def circ() -> None:
        q0 = qubit()
        q1 = qubit()
        q2 = qubit()
        h(q0)
        cx(q0, q1)
        rz(q0, pi)
        t(q1)
        toffoli(q0, q1, q2)
        x(q2)
        measure(q0)
        measure(q1)
        measure(q2)

    gate_counts, n_qubits = extract_gate_counts(circ.compile())

    assert n_qubits == 3
    assert gate_counts.t == 1
    assert gate_counts.toffoli == 1
    assert gate_counts.rotation == 1
    assert gate_counts.measurement == 3
    # h(q0), cx(q0,q1), x(q2) -> 3 clifford ops
    assert gate_counts.clifford == 3


def test_empty_circuit_has_zero_counts():
    @guppy
    def circ() -> None:
        q0 = qubit()
        discard(q0)

    gate_counts, n_qubits = extract_gate_counts(circ.compile())

    assert n_qubits == 1
    assert gate_counts.t == 0
    assert gate_counts.toffoli == 0
    assert gate_counts.rotation == 0
    assert gate_counts.measurement == 0
    assert gate_counts.clifford == 0


def test_conditional_raises_control_flow_not_supported():
    @guppy
    def circ() -> None:
        q0 = qubit()
        ctrl = qubit()
        h(ctrl)
        b = measure(ctrl)
        if b:
            h(q0)
        else:
            x(q0)
        discard(q0)

    with pytest.raises(ControlFlowNotSupported):
        extract_gate_counts(circ.compile())
