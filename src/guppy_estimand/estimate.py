"""Top-level API: compiled guppy program -> physical resource estimate.

This is an adapter, not a resource-estimation engine: the actual surface-code
cost models (physical qubit count, runtime, error) are Qualtran's
``qualtran.surface_code.PhysicalCostModel``, which implements the formulas
from Beverland et al. 2022 (arXiv:2211.07629) and Gidney & Fowler's
CCZ-factory model. See CLAUDE.md for citations and the reasoning behind
reusing Qualtran instead of re-deriving these formulas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from hugr.hugr.base import Hugr
from hugr.package import Package
from qualtran.resource_counting import GateCounts
from qualtran.surface_code import AlgorithmSummary, PhysicalCostModel

from guppy_estimand.gate_counts import extract_gate_counts

Scheme = Literal["beverland", "gidney_fowler"]


@dataclass(frozen=True)
class EstimateResult:
    scheme: Scheme
    data_d: int
    n_algo_qubits: int
    gate_counts: GateCounts
    n_phys_qubits: int
    duration_hr: float
    error: float

    def __str__(self) -> str:
        return (
            f"guppy-estimand result (scheme={self.scheme}, code distance d={self.data_d})\n"
            f"  logical qubits:    {self.n_algo_qubits}\n"
            f"  logical gates:     {self.gate_counts}\n"
            f"  physical qubits:   {self.n_phys_qubits:,}\n"
            f"  runtime:           {self.duration_hr:.3e} hours\n"
            f"  total error:       {self.error:.3e}"
        )


def _build_model(scheme: Scheme, data_d: int, **scheme_kwargs) -> PhysicalCostModel:
    if scheme == "beverland":
        return PhysicalCostModel.make_beverland_et_al(data_d=data_d, **scheme_kwargs)
    if scheme == "gidney_fowler":
        return PhysicalCostModel.make_gidney_fowler(data_d=data_d, **scheme_kwargs)
    raise ValueError(f"unknown scheme {scheme!r}, expected 'beverland' or 'gidney_fowler'")


def estimate(
    compiled: Package | Hugr,
    *,
    scheme: Scheme = "beverland",
    data_d: int = 17,
    **scheme_kwargs,
) -> EstimateResult:
    """Estimate physical qubit count, runtime, and error for a compiled guppy program.

    Args:
        compiled: The return value of a ``@guppy``-decorated function's
            ``.compile()`` method, or a ``hugr.Hugr`` directly.
        scheme: Which surface-code cost model to use. ``"beverland"`` follows
            Beverland et al. 2022 (arXiv:2211.07629); ``"gidney_fowler"``
            follows Gidney & Fowler's CCZ magic-state factory model. Both are
            Qualtran's implementations, not reimplemented here.
        data_d: Surface-code distance for the data block. This is NOT
            optimized for the target error budget in v1 -- callers must pick
            a distance and check the resulting `error` themselves. See
            CLAUDE.md "Known limitations".
        **scheme_kwargs: Forwarded to
            ``PhysicalCostModel.make_beverland_et_al`` /
            ``.make_gidney_fowler`` (e.g. ``data_block_name``, ``factory_ds``
            for beverland).

    Raises:
        ControlFlowNotSupported: if the program contains a conditional or
            loop (v1 only supports straight-line programs).
        UnrecognizedGate: if the program uses a quantum op with no known
            GateCounts classification.
    """
    gate_counts, n_qubits = extract_gate_counts(compiled)
    algo_summary = AlgorithmSummary(n_algo_qubits=n_qubits, n_logical_gates=gate_counts)
    model = _build_model(scheme, data_d, **scheme_kwargs)

    return EstimateResult(
        scheme=scheme,
        data_d=data_d,
        n_algo_qubits=n_qubits,
        gate_counts=gate_counts,
        n_phys_qubits=model.n_phys_qubits(algo_summary),
        duration_hr=model.duration_hr(algo_summary),
        error=model.error(algo_summary),
    )
