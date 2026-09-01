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
    is_upper_bound: bool = False
    """True if this result came from upper_bound=True mode: gate_counts
    (and everything downstream) is a worst-case bound over all branches/
    loop iterations, NOT a point estimate. See CLAUDE.md 'Bounded control
    flow (opt-in)'."""

    def __str__(self) -> str:
        header = f"guppy-estimand result (scheme={self.scheme}, code distance d={self.data_d})"
        if self.is_upper_bound:
            header += "\n  *** UPPER BOUND -- NOT a point estimate (upper_bound=True) ***"
        lines = [
            header,
            f"  logical qubits:    {self.n_algo_qubits}",
            f"  logical gates:     {self.gate_counts}",
            f"  physical qubits:   {self.n_phys_qubits:,}"
            + ("  (upper bound)" if self.is_upper_bound else ""),
            f"  runtime:           {self.duration_hr:.3e} hours"
            + ("  (upper bound)" if self.is_upper_bound else ""),
            f"  total error:       {self.error:.3e}" + ("  (upper bound)" if self.is_upper_bound else ""),
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


# --- Auto-selecting data_d for a target total error budget ---
#
# See CLAUDE.md "Auto-selecting data_d" for the full derivation. Short
# version: model.error(algo_summary), for a fixed scheme/gate-counts/
# physical-error-rate, was verified BY HAND (not assumed) to be
# monotonically non-increasing in data_d, with a real floor -- not a
# rounding artifact -- once the magic-state factory's own error
# contribution (which does NOT depend on data_d; it depends only on
# factory_ds, a separate parameter) dominates the data block's own
# contribution (which decays roughly exponentially in data_d, per
# QECScheme.logical_error_rate's a*(p/p*)**((d+1)/2) form). This makes
# bisection valid, but it also means a target_error set below that floor
# is genuinely unachievable by ANY data_d for the given scheme/gate counts
# -- not a bug, not a search-bound-too-small problem -- and must fail
# loudly rather than silently return the largest distance tried.
#
# Search is restricted to odd d >= 3, matching Qualtran's own convention:
# QECScheme.code_distance_from_budget() (a similar, but narrower, existing
# Qualtran utility -- see CLAUDE.md for why we don't just call it directly)
# always returns an odd d, clamped to a minimum of 3, and Qualtran's own
# test suite (qec_scheme_test.py::test_invert_error_at) asserts
# `d % 2 == 1` on its result. d=1 is excluded on the same grounds Qualtran
# itself excludes it: a distance-1 surface code corrects zero errors, so
# it isn't a meaningful "smallest code distance" to offer as an answer.
_MIN_SEARCH_D = 3
_MAX_SEARCH_D = 100_001
"""Hard sanity cap on the bisection search, in the sense of CLAUDE.md's
"no reasonable data_d achieves this" -- not a guess at a typical distance.
Real surface-code distances in the literature top out around a few
hundred; growth toward this cap is exponential (each failed probe roughly
doubles d), so reaching it costs on the order of 15-16 extra model.error()
calls, not a slow crawl. If growth reaches this cap without achieving
target_error, _select_data_d_for_target_error raises rather than returning
d=100_001 as if it were a real answer."""


def _select_data_d_for_target_error(
    scheme: Scheme, target_error: float, algo_summary: AlgorithmSummary, **scheme_kwargs
) -> int:
    """Smallest odd code distance d >= 3 whose model.error(algo_summary) is
    <= target_error, found by bisection over the SAME PhysicalCostModel
    pipeline _build_model()/estimate() otherwise uses for a fixed data_d --
    not a separate, hand-derived error formula. See the module-level
    comment above and CLAUDE.md "Auto-selecting data_d" for why bisection
    is valid (verified monotonicity) and why the search is odd-only.
    """
    if not (target_error > 0):
        raise ValueError(f"target_error must be a positive number, got {target_error!r}")

    def error_at(d: int) -> float:
        return _build_model(scheme, d, **scheme_kwargs).error(algo_summary)

    lo_d = _MIN_SEARCH_D
    lo_error = error_at(lo_d)
    if lo_error <= target_error:
        return lo_d

    hi_d = lo_d
    hi_error = lo_error
    while hi_error > target_error:
        if hi_d >= _MAX_SEARCH_D:
            raise ValueError(
                f"No code distance up to d={_MAX_SEARCH_D} achieves target_error="
                f"{target_error:.3e} for scheme={scheme!r} (achieved error="
                f"{hi_error:.3e} at d={hi_d}). Increasing data_d only reduces the "
                "data block's own error contribution -- it never reduces the magic "
                "state factory's, which is independent of data_d (see CLAUDE.md "
                "'Auto-selecting data_d'), so a target below the factory's own error "
                "floor can never be reached by any data_d. Try a looser target_error, "
                "different scheme_kwargs (e.g. smaller factory_ds), or supply data_d "
                "directly and inspect EstimateResult.error yourself."
            )
        hi_d = min(2 * hi_d + 1, _MAX_SEARCH_D)  # 2*odd+1 is odd; stays odd at the cap too
        hi_error = error_at(hi_d)

    # Bisect on the index k (d = 2k+1) between lo_d (error > target, known
    # too small) and hi_d (error <= target, known to work) for the
    # smallest d that still achieves the target. Correct even across the
    # error-vs-d plateau confirmed above: bisection only ever needs "is
    # this d's error <= target", never strict monotonic separation between
    # neighboring probes.
    lo_k, hi_k = (lo_d - 1) // 2, (hi_d - 1) // 2
    while hi_k - lo_k > 1:
        mid_k = (lo_k + hi_k) // 2
        mid_d = 2 * mid_k + 1
        if error_at(mid_d) <= target_error:
            hi_k = mid_k
        else:
            lo_k = mid_k
    return 2 * hi_k + 1


def estimate(
    compiled: Package | Hugr,
    *,
    scheme: Scheme = "beverland",
    data_d: int | None = None,
    target_error: float | None = None,
    upper_bound: bool = False,
    loop_trip_counts: dict[int, int] | None = None,
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
        data_d: Surface-code distance for the data block, fixed by the
            caller. Mutually exclusive with ``target_error`` -- exactly one
            of the two must be supplied.
        target_error: Instead of a fixed ``data_d``, auto-select the
            smallest odd code distance (>= 3) whose resulting ``error`` is
            <= this budget, via bisection over the same
            ``PhysicalCostModel.error()`` this module already uses for a
            fixed ``data_d`` -- not a separate, hand-derived formula. See
            CLAUDE.md "Auto-selecting data_d" for the verified monotonicity
            this relies on, and its caveats (e.g. it can never reach an
            error below the magic-state factory's own, ``data_d``-
            independent error floor -- see the ``ValueError`` below).
            Mutually exclusive with ``data_d``.
        upper_bound: If True, opt into worst-case bounding for programs with
            conditionals/loops instead of raising ControlFlowNotSupported:
            every conditional contributes the max of its branches (only one
            ever runs), and every loop's gate count is multiplied by a
            caller-supplied trip count from ``loop_trip_counts``. The
            resulting ``EstimateResult`` is a genuine upper bound, not a
            point estimate -- see CLAUDE.md "Bounded control flow (opt-in)".
        loop_trip_counts: Required if the program contains a loop and
            ``upper_bound=True``. Maps a loop's HUGR header-block node ID
            (an int) to its trip count. Never guessed or defaulted --
            ``LoopTripCountMissing`` names any loop you didn't supply a
            count for.
        **scheme_kwargs: Forwarded to
            ``PhysicalCostModel.make_beverland_et_al`` /
            ``.make_gidney_fowler`` (e.g. ``data_block_name``, ``factory_ds``
            for beverland).

    Raises:
        ValueError: neither or both of ``data_d``/``target_error`` were
            supplied; or ``target_error`` was supplied but no code distance
            up to this module's search cap achieves it (the error message
            names the achieved error at the search boundary -- see
            CLAUDE.md "Auto-selecting data_d").
        ControlFlowNotSupported: the program contains a conditional or loop
            and ``upper_bound`` is False (v1's default is straight-line
            programs only).
        UnrecognizedGate: the program uses a quantum op with no known
            GateCounts classification.
        LoopTripCountMissing: ``upper_bound=True`` and a loop's header has
            no entry in ``loop_trip_counts``.
        UnsupportedControlFlowShape: ``upper_bound=True`` and the program's
            control flow has a shape not hand-verified as boundable (e.g. a
            ``for`` loop over an iterator, or a loop with an internal
            ``break``) -- see CLAUDE.md.
    """
    gate_counts, n_qubits = extract_gate_counts(
        compiled, upper_bound=upper_bound, loop_trip_counts=loop_trip_counts
    )
    algo_summary = AlgorithmSummary(n_algo_qubits=n_qubits, n_logical_gates=gate_counts)

    if (data_d is None) == (target_error is None):
        raise ValueError(
            "estimate() requires exactly one of `data_d` (a fixed code distance) or "
            "`target_error` (auto-select the smallest odd code distance achieving this "
            "total error budget) -- got "
            + ("neither" if data_d is None else "both")
        )
    if target_error is not None:
        data_d = _select_data_d_for_target_error(scheme, target_error, algo_summary, **scheme_kwargs)

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
        is_upper_bound=upper_bound,
    )
