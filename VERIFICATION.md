# VERIFICATION.md — checking Qualtran's "Beverland" cost model against the actual papers

Date: 2026-08-31 (two passes, same day). Qualtran version: 0.7.0 (installed
at `.venv/Lib/site-packages/qualtran`). Three papers checked, all fetched
directly from arXiv and read page-by-page (not taken from surveys or
secondary summaries):

- Beverland, Murali, Troyer et al., *Assessing requirements to scale to
  practical quantum advantage*, arXiv:2211.07629 — §1-3.
- Litinski, *Magic State Distillation: Not as Costly as You Think*,
  arXiv:1905.06903 — §6-7.
- Litinski, *A Game of Surface Codes: Large-Scale Quantum Computing with
  Lattice Surgery*, arXiv:1808.02892 — §8.

**First-pass headline (§1-4)**: the equation CLAUDE.md originally cited
(Eq. D3) is real, and Qualtran's implementation of it is faithful — but that
implementation is not what `guppy_estimand.estimate()` actually calls. The
code path our project actually uses (`PhysicalCostModel.make_beverland_et_al()`)
computes physical qubits/runtime/error from a different set of formulas,
only some of which come from the Beverland paper.

**Second-pass headline (§6-8)**: of the other two components that
`make_beverland_et_al()` actually uses (the magic-state factory and the data
block, both cited to Litinski papers, left unchecked after the first pass —
see old §3c), the factory's core formulas check out exactly, but the data
block does not: `CompactDataBlock` is missing an additive `+3` tiles
constant present in its own cited source, and the factory's noisy-circuit
error simulation — while itself a faithful reimplementation of Litinski's
protocol — is fed Beverland's logical-error constant rather than Litinski's
own inside the composite preset, giving a different error number than
either paper would produce on its own. See §9 for the full updated summary
table.

## 1. The most important finding: two separate "Beverland" code paths in Qualtran

Qualtran ships **two independent implementations** connected to the
Beverland paper, and they are not wired together:

- `qualtran/surface_code/beverland_et_al_model.py` — free functions
  `minimum_time_steps()`, `code_distance()`, `t_states()`, each with an
  inline docstring citing arXiv:2211.07629 and a specific equation (D3, D4).
  This is the code CLAUDE.md's citation pointed at.
- `qualtran/surface_code/physical_cost_model.py` — the `PhysicalCostModel`
  class, whose `.n_phys_qubits()`, `.duration_hr()`, `.error()` methods are
  what `guppy_estimand.estimate.estimate()` (`src/guppy_estimand/estimate.py`)
  actually calls, via `PhysicalCostModel.make_beverland_et_al(data_d=...)`.

I grepped the installed package for every caller of `minimum_time_steps`,
`code_distance`, and `t_states`. They are called from exactly one place:
`qualtran/surface_code/ui.py` (Qualtran's own Streamlit demo app) and their
own test file. **`PhysicalCostModel` never calls them.** So, from
`guppy_estimand`'s perspective, the D3/D4-citing code is dead — reachable
only through Qualtran's separate UI, not through the object our project
uses.

Instead, `PhysicalCostModel.make_beverland_et_al()`
(`physical_cost_model.py:160-188`) assembles its answer from four other
pieces:

| Component | Class | Cited reference |
|---|---|---|
| Physical error rate & cycle time | `PhysicalParameters.make_beverland_et_al()` | arXiv:2211.07629 (Beverland et al.) |
| Logical error rate formula | `QECScheme.make_beverland_et_al()` | functional form: arXiv:1808.06709 (Fowler & Gidney); constants: arXiv:2211.07629 |
| Data block (qubit layout) | `CompactDataBlock` (default) | arXiv:1808.02892 (Litinski, "A Game of Surface Codes") |
| Magic state factory | `FifteenToOne(9, 3, 3)` | arXiv:1905.06903 (Litinski, "Magic State Distillation: Not as Costly as You Think") |

So the name `make_beverland_et_al` is accurate for two of its four inputs
(physical parameters, QEC-scheme constants) and not for the other two (data
block layout, magic-state factory cost, which are Litinski's models, reused
here rather than Beverland's own Appendix D/E PSSPC layout and its
factory-selection procedure, Eq. E2-E6).

**This means the "we did not re-derive Eq. D3" caveat in the old CLAUDE.md
was slightly the wrong worry: Eq. D3 turns out to be correctly implemented
(see §2) but irrelevant to our output, because our output doesn't go through
it.** The real open question was always "does the code `estimate.py` actually
calls match what its `make_beverland_et_al` name implies" — and the answer is
"partially."

## 2. Checking Eq. D3 and D4 anyway (since it's what CLAUDE.md cited)

Even though this code isn't on our project's call path, it's still cited by
name in our documentation, so it's worth checking honestly rather than
leaving the claim unverified.

**Paper text (arXiv:2211.07629, PDF page 30, Appendix D), transcribed
verbatim:**

> The total number Cmin of logical time steps is therefore
>
> C_min = (M_meas + M_R + M_T) + ⌈A·log2(M_R/ε_syn) + B⌉·D_R + 3·M_Tof.  (D3)

and (same page):

> Finally, using Eq. (D2) and noting that four T states are sufficient to
> implement Toffoli, the number of T states M is given by
>
> M = ⌈A·log2(M_R/ε_syn) + B⌉·M_R + 4·M_Tof + M_T.  (D4)

D3/D4 depend on Eq. D2 (PDF page 29):

> R_T(ε′) = ⌈A·log2(1/ε′) + B⌉, ... We assume the Clifford+T synthesis in
> Table 1 of Ref. [78], which results in A = 0.53 and B = 5.3.

**Qualtran's code**, `beverland_et_al_model.py:27-77` (`minimum_time_steps`)
and `:109-128` (`n_discrete_logical_gates`, called by `t_states`):

```python
M = alg.n_logical_gates.total_beverland_count()
c_min = M['meas'] + M['R'] + M['T'] + 3 * M['Tof']
eps_syn = error_budget / 3
if M['R'] > 0:
    rot_err_budget = eps_syn / M['R']
    rotation_cost = rotation_model.rotation_cost(rot_err_budget) + rotation_model.preparation_overhead(rot_err_budget)
    ...
    c_min += math.ceil(M['D_R'] * (rotation_cost.t + 4 * rotation_cost.toffoli))
```

with the default rotation model, `rotation_cost_model.py:98`:

```python
BeverlandEtAlRotationCost = RotationLogarithmicModel(slope=0.53, overhead=5.3, gateset='Clifford+T')
```

and `RotationLogarithmicModel.rotation_cost()` (`rotation_cost_model.py:61-62`):

```python
def rotation_cost(self, error_budget: float) -> GateCounts:
    return GateCounts(t=math.ceil(-self.slope * math.log2(error_budget) + self.overhead))
```

**Term-by-term check:**
- `A = 0.53`, `B = 5.3` — exact match to the paper's stated values.
- `rotation_cost(eps_syn/M_R).t = ceil(-0.53·log2(eps_syn/M_R) + 5.3) = ceil(0.53·log2(M_R/eps_syn) + 5.3)`
  — exactly `⌈A·log2(M_R/ε_syn)+B⌉`, matching D2 evaluated at `ε′ = ε_syn/M_R`, which is exactly the substitution the paper's D3 derivation uses. (Qualtran's code comment even flags the sign inversion explicitly and gets it right.)
- `c_min = M_meas + M_R + M_T + 3·M_Tof + ceil(D_R · (rotation_cost.t + 4·rotation_cost.toffoli))`.
  For the default model, `rotation_cost.toffoli = 0` and `rotation_cost.t` is already an
  integer (produced by `math.ceil` one line above), so `D_R · rotation_cost.t` is already
  an integer and the outer `math.ceil` is a no-op — the term reduces exactly to
  `D_R · ⌈A·log2(M_R/ε_syn)+B⌉`, matching D3's middle term exactly. (I initially suspected
  a ceiling-placement bug here — ceiling a product vs. multiplying by an already-ceiled
  value aren't generally the same operation — but checked it concretely and for the default
  `BeverlandEtAlRotationCost` model the two coincide because the inner value is already an
  integer. This would only diverge from D3 if a different `rotation_model` with fractional
  or Toffoli-based cost were passed in, which is a documented Qualtran generalization beyond
  what the paper's Eq. D2 covers, not a bug.)
- `D_R` — the paper defines this as "the number of layers containing at least one rotation."
  Qualtran's code and its own docstring (`_bloq_counts.py:267-270`) admit they don't compile
  circuits into layers and instead default `D_R` to `M_R` (the rotation count) unless the
  caller explicitly supplies `n_rotation_layers`. This is a documented approximation, not a
  silent error — but it means `minimum_time_steps()` without an explicit layer count is an
  upper bound, not the paper's exact `C_min`, whenever a real circuit has rotations sharing a
  layer. Worth knowing if anyone in the future does wire `guppy_estimand` to this function.
- Eq. D4 (`t_states`/`n_discrete_logical_gates` + `GateCounts.total_t_count(ts_per_toffoli=4)`
  default, `_bloq_counts.py:186-201`) reduces to `M_T + M_R·⌈A·log2(M_R/ε_syn)+B⌉ + 4·M_Tof`
  — exact match to D4.

**Conclusion for this section: Eq. D3 and D4 are faithfully implemented** in
`beverland_et_al_model.py`, constants and functional form both verified
against the primary source. But, per §1, this module is not invoked by
`guppy_estimand`.

## 3. Checking what our code *does* use, against the paper

### 3a. `QECScheme.make_beverland_et_al()` — verified, exact match

Paper, Table V (PDF page 21), surface code / gate-based qubits row,
transcribed verbatim:

> P_sur(d) = 0.03·(p/0.01)^((d+1)/2)   n_sur(d) = 2d²   τ_sur(d) = (4t_gate + 2t_meas)·d

Qualtran, `qec_scheme.py:100-108`:

```python
@classmethod
def make_beverland_et_al(cls):
    return cls(error_rate_scaler=0.03, error_rate_threshold=0.01)
```

and `logical_error_rate()` (`qec_scheme.py:48-70`) computes
`error_rate_scaler * (physical_error/error_rate_threshold)^((d+1)/2)`.
Substituting: `0.03 * (p/0.01)^((d+1)/2)` — **exact match** to `P_sur(d)`,
including both constants.

The `n_sur(d) = 2d²` term is implemented in `data_block.py:101-104`
(`n_phys_per_tile = 2 * self.data_d**2`) — exact match.

Qualtran attributes the *functional form* of `logical_error_rate` to Fowler
& Gidney 2018 (arXiv:1808.06709) rather than to Beverland's Table V directly
— reasonable, since Table V's own formula derivation isn't self-contained in
the Beverland paper either ("the pre-factor a and threshold p* can be
extracted numerically from simulations," per the paper's own text on PDF
page 21) and the paper cites Refs. [38] and [141] for it. I did not chase
those two further references — noting this as unverified provenance, one
level removed, same as the Beverland paper itself leaves it.

### 3b. `PhysicalParameters.make_beverland_et_al()` — verified, exact match

Paper, Appendix A (PDF page 20), describing the "(ns, 10⁻³)" / "(ns, 10⁻⁴)"
superconducting qubit examples:

> We project 50 ns gate times and 100 ns measurement times for future
> systems... We evaluate two cases, with 10⁻³ and 10⁻⁴ two-qubit gate error
> rates, respectively, as realistic and optimistic targets.

Qualtran, `physical_parameters.py:31-76`: `superconducting` branch sets
`t_gate_ns = 50`, `t_meas_ns = 100`; `phys_err_rate` is `1e-3` unless
`optimistic_err_rate=True`, in which case `1e-4`. `cycle_time_ns = 4*t_gate_ns
+ 2*t_meas_ns = 400`, i.e. `cycle_time_us = 0.4`. **Exact match** to the
paper's stated values and to Table V's `τ_sur(d) = (4t_gate + 2t_meas)·d`
formula (Qualtran's `duration_hr()` multiplies `cycle_time_us` by a cycle
count that already includes the factor of `d`, via `data_block.n_cycles()`
— so the `d` dependence is applied downstream, but the per-cycle constant
matches).

As an independent cross-check, not reused from Qualtran's own worked
example: the paper's own quantum-chemistry worked example (PDF page 34)
states `τ(d) = 6.8 μs` at `d = 17`. `400 ns × 17 = 6800 ns = 6.8 μs` —
matches, confirming the formula and constants together, using a number the
paper computed independently of Qualtran.

### 3c. `CompactDataBlock` and `FifteenToOne` — now checked, see §6/§7

The previous pass of this file left these unchecked. **Update (2026-08-31,
second verification pass): both have now been checked against their cited
papers.** Headline results, detailed in §6 and §7 below:

- `FifteenToOne`'s qubit-count and cycle-count formulas are an **exact
  match** to arXiv:1905.06903 (confirmed on the paper's own printed page
  11, matching Qualtran's own citation). Its internal noisy-circuit
  simulation is also structurally faithful — using the *paper's own*
  logical-error constant reproduces the paper's own published output-error
  number to 4 significant figures. But — important caveat — the composite
  `make_beverland_et_al()` preset does **not** use the paper's own constant
  for this; it substitutes Beverland's, giving a different (smaller) factory
  error than Litinski's paper would predict for the same `(d_X,d_Z,d_m)`.
  See §7.
- `CompactDataBlock.n_tiles()` **does not match** its cited paper. The paper
  (arXiv:1808.02892, page 7, Figure 9 — exactly the location Qualtran's own
  docstring cites) states the compact block uses `1.5n + 3` tiles; Qualtran's
  code computes `ceil(1.5*n)`, silently dropping the `+3`. This is a real,
  reproducible discrepancy, not a rounding or edge-case issue — see §6.

## 4. Hand-reproduced number

To close the loop on whether Qualtran's own code is at least internally
consistent with the formulas it cites (as opposed to a hidden bug), I
computed, independently by hand from the algebraic formulas found in
source — not by calling `PhysicalCostModel` — the physical qubit count for
this project's own example, `examples/bell_and_t.py`
(`t=1, clifford=2, measurement=2`, `n_algo_qubits=2`, `data_d=17`, default
`factory_ds=(9,3,3)`, default `data_block_name='compact'`):

**Factory** (`FifteenToOne.n_physical_qubits()`, `fifteen_to_one_factory.py:52-54`,
`d_X=9, d_Z=3, d_m=3`):

```
2*(d_X + 4*d_Z)*3*d_X + 4*d_m
= 2*(9 + 12)*3*9 + 4*3
= 2*21*27 + 12
= 1134 + 12
= 1146
```

**Data block** (`CompactDataBlock`, `data_block.py:169-170` for tiles,
`:101-104` for phys-qubits-per-tile, `data_d=17`, `n_algo_qubits=2`):

```
n_tiles = ceil(1.5 * 2) = 3
n_phys_per_tile = 2 * 17^2 = 578
n_data_phys_q = 578 * 3 = 1734
```

**Total:**

```
1146 (factory) + 1734 (data block) = 2880
```

**Qualtran's actual output** (`PhysicalCostModel.make_beverland_et_al(data_d=17).n_phys_qubits(algo_summary)`),
run live during this verification:

```
factory.n_physical_qubits()               = 1146
data_block.n_physical_qubits(n_algo_qubits=2) = 1734
model.n_phys_qubits(algo_summary)          = 2880
```

**These agree exactly** — and both match the number already published in
`README.md` from running `examples/bell_and_t.py` end-to-end. This confirms
Qualtran's arithmetic for `n_phys_qubits()` matches its own documented,
cited formulas — i.e. Qualtran's code computes what Qualtran's code claims
to compute, and our adapter plumbs `GateCounts`/`AlgorithmSummary` through
without introducing an error. **It does not confirm the formulas themselves
are transcribed correctly from the cited papers.** §6/§7 (added in the
second verification pass, below) check that, and find the factory formula
(1146) is correct but the data-block formula (1734) is not — it should be
3468 per the cited paper. See §6 for the corrected hand computation.

## 6. `FifteenToOne` vs. arXiv:1905.06903 — exact match

**Paper**: Litinski, *Magic State Distillation: Not as Costly as You Think*,
arXiv:1905.06903 (confirmed via `arxiv.org/abs/1905.06903` — title and
single-author "Daniel Litinski" match Qualtran's docstring exactly). PDF
fetched directly and read; printed page 11 (PDF page index 10, footer
"Accepted in Quantum 2019-10-30... 11") states, verbatim:

> In total, this 15-to-1 protocol has a space cost of `2·(dX+4dZ)·3dX+4dm`
> physical qubits, taking physical measurement ancillas into account. The
> time cost is `6dm/(1−pfail)` code cycles, where `pfail` is the failure
> probability of the protocol.

This is the exact sentence Qualtran's own inline comments point at
("`# source: page 11 of https://arxiv.org/abs/1905.06903`",
`fifteen_to_one_factory.py:53` and `:94`). Qualtran's code:

```python
def n_physical_qubits(self) -> int:
    return 2 * (self.d_X + 4 * self.d_Z) * 3 * self.d_X + 4 * self.d_m

def n_cycles(self, n_logical_gates, logical_error_model) -> int:
    num_t = n_logical_gates.total_t_count()
    return np.ceil(num_t * 6 * self.d_m / (1 - self.p_fail(logical_error_model)))
```

**Exact term-by-term match** to the paper's stated formula, including the
constant coefficients (2, 4, 3, 4, 6). (`n_cycles` multiplies the paper's
per-state cost by `num_t`, the total number of T states needed — a
reasonable, undocumented-but-obvious generalization from "cost of one magic
state" to "cost of producing all the magic states this circuit needs
sequentially from one factory," not a deviation from the formula itself.)

**Hand reproduction of 1146**, direct from the paper's formula, `d_X=9,
d_Z=3, d_m=3` (Qualtran's default `factory_ds`):

```
2*(9 + 4*3)*3*9 + 4*3 = 2*21*27 + 12 = 1134 + 12 = 1146
```

Matches Qualtran's `FifteenToOne(9,3,3).n_physical_qubits()` exactly (§4).
**This part of the 2,880 total is correct.**

**The internal noisy-circuit simulation** (`_build_factory`, used for
`p_fail`/`p_out`, which feed `factory_error()` and `n_cycles()`) is a `cirq`
density-matrix simulation of the 5-qubit 15-to-1 circuit, using per-gate
error terms of the form `0.5*(d_m/d_Z)*pz*d_m` etc. These structurally match
the paper's Section 3 error analysis (page 6-10), which builds up the same
kind of terms (e.g. "`0.5(dZ/dX)·pL(pphys,dX)`" for the X-error probability
on qubits 2-5, PDF page 6) from a logical error rate function `pL(pphys,d)`.
I did not exhaustively re-derive every one of the ~15 per-gate error terms
in `_build_factory` against the paper's text term-by-term (this would mean
re-deriving the full circuit-level error propagation the paper spends four
pages on) — but I did find and check the paper's own definition of `pL`,
and used it for a decisive end-to-end numeric check instead (next section).

## 7. The `pL` (logical error rate) constant: FifteenToOne's *use* of it is correct, but `make_beverland_et_al()` substitutes a different constant than the paper's own

The paper defines, PDF page 6, Eq. (7):

> The logical error rate per code cycle can be approximated as
> `pL(pphys,d) = 0.1*(100*pphys)^((d+1)/2)`.

Rewritten in the `a*(p/p*)^((d+1)/2)` form used elsewhere in this project:
`pL(p,d) = 0.1*(p/0.01)^((d+1)/2)`, i.e. **`a = 0.1`, `p* = 0.01`**.

This is *not* the same `a` as Beverland's Table V value (`a = 0.03`,
same `p* = 0.01`) checked in §3a. Two different papers, two different
numeric constants for the same-shaped surface-code logical-error formula
— unsurprising on its own (different papers, different assumed decoders/
simulations), but it matters here because Qualtran's `FifteenToOne` doesn't
hardcode Litinski's own constant — it takes a `LogicalErrorModel` as a
parameter and uses whatever the caller passes in
(`_build_factory(..., logical_error_model=logi_err_model)`, using
`px = logical_error_model(d_X)` etc.). This is a deliberate, reasonable
composability choice by Qualtran (one QEC-scheme assumption applied
consistently across factory and data block) — but it means that when
`PhysicalCostModel.make_beverland_et_al()` builds the `LogicalErrorModel`
from `QECScheme.make_beverland_et_al()` (`a=0.03`) and hands it to
`FifteenToOne`, the factory's internal error simulation runs with
Beverland's constant, not Litinski's own.

**Direct test, to see how much this matters** — I ran Qualtran's actual
`FifteenToOne(9,3,3)` (the exact factory our `"beverland"` scheme uses) with
two different `LogicalErrorModel`s, at `physical_error=1e-4`, and compared
against the paper's own published result. The paper states (PDF page 12):
*"The other protocols reported in Tab. 1 for pphys=10⁻⁴ are (15-to-1)9,3,3
and (15-to-1)11,5,5, reducing the error to pout=9.3×10⁻¹⁰ and
pout=1.9×10⁻¹¹, respectively."*

```
Using Beverland's QECScheme (a=0.03, p*=0.01) — what make_beverland_et_al() actually uses:
    p_fail = 0.001795
    p_out  = 1.894e-10

Using Litinski's own Eq. 7 constant (a=0.10, p*=0.01):
    p_fail = 0.003648
    p_out  = 9.300e-10   <-- matches the paper's stated 9.3e-10 to the precision given

Paper (arXiv:1905.06903, Table 1): pout = 9.3e-10 for (15-to-1)_{9,3,3} at pphys=1e-4
```

This is a clean, decisive result: **when the paper's own constant is used,
Qualtran's `FifteenToOne` reproduces the paper's own published number
essentially exactly (9.300e-10 vs. 9.3e-10) — confirming the noisy-circuit
implementation itself is a faithful reimplementation of the paper's
protocol.** But our project's actual `"beverland"` scheme does not use that
constant; it uses Beverland's `a=0.03`, giving a `p_out` about 4.9× smaller
than Litinski's own paper would predict for the identical `(d_X,d_Z,d_m)`
and physical error rate. This affects `estimate()`'s `error` field (via
`factory_error()`) directly, and `duration_hr()`/`n_cycles()` slightly (via
`p_fail`, though the effect there is small since both `p_fail` values are
`≪1`).

**This is not a bug in the sense of "the code doesn't do what it says" —
`FifteenToOne` faithfully reimplements the paper's circuit and error model,
parameterized by whichever QEC scheme it's given, exactly as designed.** But
it does mean: anyone reading `"beverland"` scheme output and expecting it to
reproduce Litinski's own published magic-state-factory error numbers will
get a different (in this case, more optimistic) number, because the preset
mixes Beverland's threshold assumption into Litinski's circuit rather than
using Litinski's own.

## 8. `CompactDataBlock` vs. arXiv:1808.02892 — confirmed discrepancy (missing "+3")

**Paper**: Litinski, *A Game of Surface Codes: Large-Scale Quantum Computing
with Lattice Surgery*, arXiv:1808.02892 (confirmed via `arxiv.org/abs/1808.02892`
— title and author match Qualtran's docstring exactly). PDF fetched and read;
printed page 7 (PDF page index 6, footer "...verify 7") — again, exactly the
location Qualtran's own docstring cites ("Page 7, figure 9").

Three separate places in the paper state the same formula (cross-checked
against the ar5iv LaTeX-derived HTML rendering as well, to rule out a PDF
text-extraction artifact — all three agree):

> **Figure 9 caption**: "A compact block stores n data qubits in `1.5n+3`
> tiles. The consumption of a magic state can take up to `9τ`."
>
> **Body text** (introducing the design): "The first design that we discuss
> uses only `1.5n+3` tiles."
>
> **Summary paragraph**: "Compact blocks use `1.5n+3` tiles for n qubits and
> require up to `9τ` to consume a magic state."

Qualtran's code, `data_block.py:169-174`:

```python
class CompactDataBlock(DataBlock):
    def n_tiles(self, n_algo_qubits: int) -> int:
        return math.ceil(1.5 * n_algo_qubits)

    @property
    def n_steps_to_consume_a_magic_state(self) -> int:
        return 9
```

**The `9` (time cost) is correct — exact match.** **The tile-count formula
is not**: Qualtran computes `ceil(1.5n)`, the paper says `1.5n + 3`. This is
a straightforward, unambiguous omission of the additive `+3` constant — not
a rounding difference (`ceil` vs `floor`), not an edge case, and not
explained by anything else in `data_block.py` or `physical_cost_model.py`
(I checked — no other code path adds a compensating `+3` tiles anywhere in
the pipeline).

**Concrete effect on our project's own example** (`bell_and_t`,
`n_algo_qubits=2`, `data_d=17`):

```
Qualtran's formula:  n_tiles = ceil(1.5*2)       = 3
Paper's formula:     n_tiles = ceil(1.5*2 + 3)   = 6   (exactly double, for this n)

n_phys_per_tile = 2*17^2 = 578

Qualtran's data-block qubits:      578 * 3 = 1,734   <- matches §4's hand reproduction of Qualtran's own code
Paper-correct data-block qubits:   578 * 6 = 3,468

Qualtran's total n_phys_qubits:        1,146 (factory, correct, §6) + 1,734 = 2,880
Paper-correct total n_phys_qubits:     1,146 (factory, correct, §6) + 3,468 = 4,614
```

So: **the "hand-reproduce 1734" instruction for this task has two different
honest answers.** Reproducing *Qualtran's own coded formula* by hand gives
1,734, which is what Qualtran outputs (self-consistent, no arithmetic bug).
Reproducing *the cited paper's formula* by hand gives 3,468 — Qualtran's
number is 1,734, exactly half. **This is the most significant finding of
this verification pass**: the `n_phys_qubits` our project reports for the
`"beverland"` scheme understates the data-block qubit cost relative to the
paper it's cited from, by a fixed offset of `3 tiles * 2d² qubits/tile =
6d²` physical qubits per estimate (`6 * 17² = 1,734` at `d=17` — coincidentally
equal to the whole (wrong) data-block total in this particular example,
since `n_tiles` is small; the *absolute* qubit gap stays `6d²` regardless of
`n_algo_qubits`, so it matters less in relative terms for large algorithms,
but is a real, fixed, uncorrected undercount for every `"beverland"` +
compact-data-block estimate this project produces).

**As a secondary, lower-priority observation** (not on our project's default
path, since `make_beverland_et_al()` defaults to `data_block_name='compact'`,
not `'intermediate'`): `IntermediateDataBlock.n_tiles()` is `ceil(2n)`, but
the paper is *internally inconsistent* about this one — its Figure 13a
caption says `2.5n+4` tiles while its body text and summary both say `2n+4`
tiles (confirmed via both the PDF and the ar5iv HTML rendering — a real
inconsistency in the published paper, not an extraction artifact). Either
way, Qualtran's code is missing the "+4" constant here too, following the
same pattern as `CompactDataBlock`. I did not chase which of the paper's two
inconsistent values is the "real" one, since this data block isn't on our
call path. By contrast, **`FastDataBlock.n_tiles()` — `ceil(2n + sqrt(8n) +
1)` — matches the paper exactly** ("Fast blocks use `2n+√8n+1` tiles," PDF
page 8): so the missing-constant pattern isn't universal across all three
data block classes, just `Compact` and (probably) `Intermediate`.

## 9. Summary: what's verified, what isn't (updated after both passes)

| Claim | Status |
|---|---|
| Eq. D3 (`minimum_time_steps`) matches the paper | ✅ Verified against primary source (§2). **Not on our project's call path.** |
| Eq. D4 (`t_states`) matches the paper | ✅ Verified against primary source (§2). **Not on our project's call path.** |
| `PhysicalCostModel.make_beverland_et_al()` (what `estimate()` actually calls) uses Eq. D3/D4 | ❌ **False.** It doesn't call `beverland_et_al_model.py` at all (§1). |
| `QECScheme.make_beverland_et_al()` logical-error formula & constants match the paper's Table V | ✅ Verified against primary source, exact numeric match (§3a). |
| `PhysicalParameters.make_beverland_et_al()` (superconducting, realistic) matches the paper's Appendix A | ✅ Verified against primary source, exact numeric match, cross-checked against the paper's own worked example (§3b). |
| `FifteenToOne.n_physical_qubits()`/`n_cycles()` match arXiv:1905.06903 (page 11) | ✅ Verified, exact formula match, hand-reproduced 1,146 (§6). |
| `FifteenToOne`'s noisy-circuit simulation faithfully implements the paper's protocol | ✅ Verified — reproduces the paper's own published `p_out=9.3e-10` example to 4 sig. figs, **when using the paper's own `a=0.1` constant** (§7). |
| `make_beverland_et_al()` uses the *same* logical-error constant Litinski's paper uses for the factory | ❌ **False.** It substitutes Beverland's `a=0.03` for Litinski's own `a=0.1`, giving `p_out` ≈4.9× smaller than the paper's own number for identical `(d_X,d_Z,d_m)` (§7). Not a code bug — a documented composability choice with an unstated consequence. |
| `CompactDataBlock.n_tiles()` matches arXiv:1808.02892 (page 7, Fig. 9) | ❌ **False.** Paper says `1.5n+3` tiles (confirmed 3 independent places + ar5iv cross-check); code computes `ceil(1.5n)`, missing `+3`. Doubles the data-block qubit count for our `bell_and_t` example (1,734 actual vs. 3,468 paper-correct) (§8). |
| `FastDataBlock.n_tiles()` matches arXiv:1808.02892 | ✅ Verified, exact match (§8, secondary check). |
| `IntermediateDataBlock.n_tiles()` matches arXiv:1808.02892 | ⚠️ Unresolved — the paper itself is internally inconsistent (`2n+4` in body text/summary vs. `2.5n+4` in the Fig. 13a caption); code's `ceil(2n)` matches neither exactly. Not on our default call path (§8). |
| Qualtran's own code computes what Qualtran's own code/docs claim (internal consistency) | ✅ Verified by independent hand computation for both factory and data block (§4, §6, §8). |

**Net assessment, updated:** `guppy_estimand`'s `"beverland"` scheme output
is a composite of formulas from **three** different papers (Beverland et
al. 2211.07629 for hardware/QEC-threshold assumptions; Litinski 1905.06903
for the magic-state factory; Litinski 1808.02892 for the data block), and
this second pass found that **two of the three components have real,
verified discrepancies against their own cited sources**:

1. The magic-state factory (§7) computes a *correct implementation of the
   wrong constant* — faithful to Litinski's circuit, but parameterized with
   Beverland's threshold rather than Litinski's own, which the composite
   preset does silently and without flagging it as a choice.
2. The data block (§8) has a **literal missing term**: `CompactDataBlock`
   drops the paper's `+3` tiles additive constant, undercounting physical
   qubits (by `6d²`, i.e. 1,734 of the 4,614 paper-correct qubits for our
   own `bell_and_t` example — a 37% understatement of total `n_phys_qubits`
   for this example, shrinking in relative terms for larger `n_algo_qubits`
   since the missing term is a fixed offset, not a per-qubit factor).

Only the physical-parameters/logical-error-rate half (§3a/§3b, checked in
the first pass) and the factory's own qubit/cycle-count formulas (§6, this
pass) are clean, exact matches to their cited sources. **This means the
`n_phys_qubits` and `error` numbers `guppy_estimand` currently reports under
`scheme="beverland"` are not a faithful reproduction of any single cited
paper, including for the specific components (factory, data block) whose
docstrings claim they are** — this goes beyond the "these are two different
papers stitched together" scope-caveat from the first pass; the data-block
piece has an actual arithmetic gap against its own citation.

## Recommendation (updated)

No code changes made in this pass (verification-only, per the task). Two
concrete follow-ups this finding motivates, for whoever picks this up next:

1. **File or check for an upstream Qualtran issue** on `CompactDataBlock.n_tiles()`
   missing the `+3` constant from arXiv:1808.02892 page 7 — this looks like
   a genuine upstream bug, not an intentional simplification (nothing in the
   code or docstring flags it as one, and the `n_steps_to_consume_a_magic_state=9`
   sibling constant on the same class *is* transcribed correctly, so this
   isn't "Qualtran deliberately uses a simplified model").
2. If `guppy_estimand` needs `n_phys_qubits` to be correct rather than merely
   "whatever the currently-installed Qualtran computes," consider either (a)
   monkey-patching/wrapping `CompactDataBlock` locally with the corrected
   `1.5n+3` formula until upstream fixes it, or (b) prominently surfacing in
   `README.md`/`EstimateResult.__str__` that the `"beverland"` scheme's
   physical-qubit count is a known ~37%-for-small-n underestimate relative to
   its own cited source, so users aren't silently misled. Neither was done
   here — this file documents the finding; deciding how to act on it is a
   product decision, not something to silently patch into a verification
   pass.
3. If bit-for-bit fidelity to Beverland's own PSSPC method (not just its
   hardware assumptions) is ever needed, the correct fix is calling
   `beverland_et_al_model.minimum_time_steps()` / `code_distance()` /
   `t_states()` directly and building physical-qubit/error formulas from
   Table V ourselves — i.e., bypassing `PhysicalCostModel.make_beverland_et_al()`
   entirely — rather than assuming the preset already does this (unchanged
   from the first pass's recommendation).
