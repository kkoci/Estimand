"""Extract a Qualtran ``GateCounts`` summary from a compiled guppy/HUGR program.

See CLAUDE.md for the verified HUGR node structure this relies on (guppylang
1.0.2 / hugr 0.18.5, checked by hand against ``hugr.Hugr.nodes()`` /
``descendants()`` output -- not assumed from docs).
"""

from __future__ import annotations

from hugr import ops
from hugr.hugr.base import Hugr
from hugr.package import Package
from qualtran.resource_counting import GateCounts

# Qualified op names (``ExtOp.name()`` returns "<extension>.<op>", e.g.
# "tket.quantum.H") observed by compiling sample guppy programs and walking
# the resulting HUGR. Any quantum op not listed here causes extraction to
# fail loudly rather than silently under-count.
_CLIFFORD = {
    "tket.quantum.H",
    "tket.quantum.X",
    "tket.quantum.Y",
    "tket.quantum.Z",
    "tket.quantum.S",
    "tket.quantum.Sdg",
    "tket.quantum.V",
    "tket.quantum.Vdg",
    "tket.quantum.CX",
    "tket.quantum.CY",
    "tket.quantum.CZ",
    "tket.quantum.Reset",
}
_T_LIKE = {"tket.quantum.T", "tket.quantum.Tdg"}
_TOFFOLI = {"tket.quantum.Toffoli"}
_ROTATION = {"tket.quantum.Rx", "tket.quantum.Ry", "tket.quantum.Rz", "tket.quantum.CRz"}
_MEASUREMENT = {"tket.quantum.Measure", "tket.quantum.MeasureFree"}

# Structural / bookkeeping ops that are not gates and contribute nothing to
# the gate-count total. QAlloc/TryQAlloc are counted separately for the
# qubit count.
_QALLOC = {"tket.quantum.QAlloc", "tket.quantum.TryQAlloc"}
_IGNORED = {
    "tket.quantum.QFree",
    "tket.rotation.from_halfturns",
    "tket.rotation.from_halfturns_unchecked",
    "tket.rotation.radd",
    "tket.rotation.to_halfturns",
    "tket.rotation.symbolic_angle",
    "tket.measurement.Read",
}

# HUGR op *classes* (not ExtOps) that indicate control flow. A gate that
# appears once in the HUGR under one of these may execute zero, one, or many
# times at runtime, so a flat node-count sum over descendants would silently
# over- or under-count. v1 refuses to guess; see CLAUDE.md "Known
# limitations".
_CONTROL_FLOW_OPS = (ops.CFG, ops.Conditional, ops.TailLoop)


class ControlFlowNotSupported(NotImplementedError):
    """Raised when the HUGR contains a CFG/Conditional/TailLoop region.

    Gate counts extracted by summing over all descendant nodes are only
    correct for straight-line dataflow: a branch's gates would be counted
    even though only one branch executes, and a loop body's gates would be
    counted once regardless of how many times it actually runs. Supporting
    control flow correctly needs either an explicit trip-count/branch-taken
    annotation from the caller or worst-case bounding, neither of which v1
    implements.
    """


class UnrecognizedGate(NotImplementedError):
    """Raised when a quantum op has no known GateCounts bucket.

    This fails loudly instead of silently dropping the gate from the count,
    per the project's correctness bar (see CLAUDE.md).
    """


def _as_hugr(compiled: Package | Hugr) -> Hugr:
    if isinstance(compiled, Package):
        if len(compiled.modules) != 1:
            raise ValueError(
                f"expected a single-module Package, got {len(compiled.modules)} modules"
            )
        return compiled.modules[0]
    return compiled


def extract_gate_counts(compiled: Package | Hugr) -> tuple[GateCounts, int]:
    """Walk a compiled guppy program's HUGR and return (GateCounts, n_qubits).

    ``compiled`` is the return value of a ``@guppy``-decorated function's
    ``.compile()`` method (a ``hugr.package.Package``), or a ``hugr.Hugr``
    directly.

    Raises ``ControlFlowNotSupported`` if the program contains a
    conditional, loop, or any other control-flow region.
    """
    hugr = _as_hugr(compiled)

    t = toffoli = clifford = rotation = measurement = 0
    n_qubits = 0

    for node in hugr.descendants(hugr.entrypoint):
        op = hugr[node].op

        if isinstance(op, _CONTROL_FLOW_OPS):
            raise ControlFlowNotSupported(
                f"HUGR node {node} is a {type(op).__name__}: v1 only supports "
                "straight-line (control-flow-free) guppy programs. See "
                "CLAUDE.md 'Known limitations'."
            )

        if not isinstance(op, ops.ExtOp):
            continue

        name = op.name()

        if name in _QALLOC:
            n_qubits += 1
        elif name in _CLIFFORD:
            clifford += 1
        elif name in _T_LIKE:
            t += 1
        elif name in _TOFFOLI:
            toffoli += 1
        elif name in _ROTATION:
            rotation += 1
        elif name in _MEASUREMENT:
            measurement += 1
        elif name in _IGNORED:
            continue
        else:
            raise UnrecognizedGate(
                f"quantum op {name!r} (HUGR node {node}) has no known GateCounts "
                "bucket. Add it to gate_counts.py's classification tables, or "
                "raise an issue if you believe it should be ignored."
            )

    gate_counts = GateCounts(
        t=t, toffoli=toffoli, clifford=clifford, rotation=rotation, measurement=measurement
    )
    return gate_counts, n_qubits
