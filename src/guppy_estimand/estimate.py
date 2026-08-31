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

# See CLAUDE.md ("Update", 2026-09-01) and VERIFICATION.md for the full
# writeup. Short version: PhysicalCostModel.make_beverland_et_al() has two
# confirmed, filed-upstream discrepancies against the papers it cites.
#
#   - quantumlib/Qualtran#1943 (CompactDataBlock undercounts data-block
#     tiles by a fixed "+3", vs. arXiv:1808.02892 page 7 Fig. 9): patched
#     locally below, via guppy_estimand._qualtran_patches.CorrectedCompactDataBlock.
#     This is an unambiguous transcription bug with one correct fix.
#   - quantumlib/Qualtran#1944 (the composite preset feeds Beverland's
#     logical-error constant, a=0.03, into Litinski's factory error model
#     instead of Litinski's own a=0.1): deliberately NOT patched locally.
#     Unlike #1943, this isn't a transcription error with one correct
#     answer -- it's a genuine cross-paper composability choice (which
#     paper's threshold assumption should apply to the factory?), and
#     Qualtran's current choice (one consistent QEC-scheme threshold across
#     the whole device) is arguably as defensible as substituting Litinski's
#     own number. We surface it as a caveat (see EstimateResult.__str__)
#     rather than silently asserting our own answer is more "correct."
_BEVERLAND_QUBIT_UNDERCOUNT_ISSUE = "https://github.com/quantumlib/Qualtran/issues/1943"
_BEVERLAND_ERROR_UNDERSTATEMENT_ISSUE = "https://github.com/quantumlib/Qualtran/issues/1944"


@dataclass(frozen=True)
class EstimateResult:
    scheme: Scheme
    data_d: int
    n_algo_qubits: int
    gate_counts: GateCounts
    n_phys_qubits: int
    duration_hr: float
    error: float
    data_block_name: str | None = None
    """Which data block variant was used for scheme="beverland" (None for
    other schemes). Only used to decide which caveats apply in __str__."""

    def __str__(self) -> str:
        lines = [
            f"guppy-estimand result (scheme={self.scheme}, code distance d={self.data_d})",
            f"  logical qubits:    {self.n_algo_qubits}",
            f"  logical gates:     {self.gate_counts}",
            f"  physical qubits:   {self.n_phys_qubits:,}",
            f"  runtime:           {self.duration_hr:.3e} hours",
            f"  total error:       {self.error:.3e}",
        ]
        if self.scheme == "beverland":
            if self.data_block_name == "compact":
                lines.append(
                    "  note: physical qubits include a local fix for a confirmed Qualtran "
                    f"bug ({_BEVERLAND_QUBIT_UNDERCOUNT_ISSUE}); see CLAUDE.md."
                )
            lines.append(
                "  note: total error is understated ~4.9x vs. the cited paper's own "
                f"constant, unpatched ({_BEVERLAND_ERROR_UNDERSTATEMENT_ISSUE}); see CLAUDE.md."
            )
        return "\n".join(lines)


def _make_beverland_model(
    data_d: int, data_block_name: str = "compact", factory_ds: tuple[int, int, int] = (9, 3, 3)
) -> PhysicalCostModel:
    """Builds the same composite model as Qualtran's
    ``PhysicalCostModel.make_beverland_et_al()``, except substituting
    ``_qualtran_patches.CorrectedCompactDataBlock`` for Qualtran's own
    ``CompactDataBlock`` when ``data_block_name == "compact"`` (the
    default), to correct quantumlib/Qualtran#1943. See the module-level
    comment above and CLAUDE.md for why only this one issue is patched.
    """
    from qualtran.surface_code import (
        FastDataBlock,
        FifteenToOne,
        IntermediateDataBlock,
        PhysicalParameters,
        QECScheme,
    )

    from guppy_estimand._qualtran_patches import CorrectedCompactDataBlock

    if data_block_name == "compact":
        data_block = CorrectedCompactDataBlock(data_d=data_d)
    elif data_block_name == "fast":
        data_block = FastDataBlock(data_d=data_d)
    elif data_block_name == "intermediate":
        data_block = IntermediateDataBlock(data_d=data_d)
    else:
        raise ValueError(f"Unknown data block {data_block_name!r}")

    return PhysicalCostModel(
        physical_params=PhysicalParameters.make_beverland_et_al(),
        data_block=data_block,
        factory=FifteenToOne(*factory_ds),
        qec_scheme=QECScheme.make_beverland_et_al(),
    )


def _build_model(scheme: Scheme, data_d: int, **scheme_kwargs) -> PhysicalCostModel:
    if scheme == "beverland":
        return _make_beverland_model(data_d, **scheme_kwargs)
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
        data_block_name=scheme_kwargs.get("data_block_name", "compact") if scheme == "beverland" else None,
    )
