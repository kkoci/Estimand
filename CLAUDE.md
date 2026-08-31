# CLAUDE.md — guppy-estimand

## What this project is

A fault-tolerant physical resource estimator for guppylang/HUGR programs:
given a compiled guppy circuit, estimate physical qubit count, runtime, and
error probability under a cited surface-code scheme. This closes a real gap
— there is no such tool in the Quantinuum guppylang/HUGR/Selene ecosystem
today (confirmed 2026-08-30, see "Confirming the gap" below).

## Decision: adapter to Qualtran, not from-scratch math

**We do not re-derive surface-code resource-overhead formulas.** We adapt
guppy/HUGR programs to feed Qualtran's (Google's) already-published,
already-tested `qualtran.surface_code` cost models. Rationale below.

### What was investigated

**Qualtran** (`pip install qualtran`, https://github.com/quantumlib/Qualtran):
read the actual source of `qualtran/surface_code/` (shallow-cloned locally
for inspection, not taken from docs/snippets). Key finding: the surface-code
cost models do **not** require a full circuit or Bloq decomposition as
input. They consume a small, plain dataclass:

```python
# qualtran/resource_counting/_bloq_counts.py
class GateCounts:
    t: SymbolicInt = 0
    toffoli: SymbolicInt = 0
    cswap: SymbolicInt = 0
    and_bloq: SymbolicInt = 0
    clifford: SymbolicInt = 0
    rotation: SymbolicInt = 0
    measurement: SymbolicInt = 0
```

wrapped in `qualtran.surface_code.AlgorithmSummary(n_algo_qubits, n_logical_gates)`,
fed to `PhysicalCostModel.make_beverland_et_al(...)` or
`.make_gidney_fowler(...)`, which expose `.n_phys_qubits()`, `.duration_hr()`,
`.error()`. This is a *much* smaller adapter target than reimplementing HUGR
ops as Qualtran `Bloq`s.

The Beverland cost model (`qualtran/surface_code/beverland_et_al_model.py`)
cites its formulas inline, e.g.:

```
References:
    https://arxiv.org/abs/2211.07629.
    Equation D3.
```
— Beverland, Murali, Troyer et al., "Assessing requirements to scale to
practical quantum advantage" (arXiv:2211.07629).

**Update (2026-08-31, two verification passes): all three components behind
`PhysicalCostModel.make_beverland_et_al()` — the function `estimate.py`
actually calls — have now been checked against their cited papers. See
`VERIFICATION.md` for the full derivation, page-by-page citations, and
hand-reproduced numbers. Do not treat `scheme="beverland"`'s output as a
faithful reproduction of any single cited paper: two real, confirmed
discrepancies were found, not just a scope/naming caveat.**

Summary of both passes:
- Eq. D3/D4 (what this citation originally pointed at) check out exactly
  against arXiv:2211.07629 (constants A=0.53/B=5.3, functional form
  confirmed by direct PDF read) — **but `beverland_et_al_model.py` is dead
  code from this project's perspective**; `PhysicalCostModel.make_beverland_et_al()`
  never calls it (`VERIFICATION.md` §1-2).
- `PhysicalParameters.make_beverland_et_al()` and `QECScheme.make_beverland_et_al()`
  (physical error rate, cycle time, logical-error-rate formula) — **verified
  exact matches** to the paper's Appendix A and Table V (§3a-3b).
- `FifteenToOne` (the magic-state factory, cited to Litinski arXiv:1905.06903)
  — qubit/cycle-count formulas are an **exact match** to the paper's printed
  page 11 (hand-reproduces 1,146 physical qubits for our `bell_and_t`
  example). Its noisy-circuit error simulation is also a faithful
  reimplementation — it reproduces the paper's own published `p_out` number
  to 4 significant figures **when given the paper's own logical-error
  constant (a=0.1)**. But the composite `make_beverland_et_al()` preset
  substitutes Beverland's constant (a=0.03) instead, silently, giving a
  factory error ≈4.9× smaller than Litinski's own paper would predict for
  the same parameters (§6-7).
- `CompactDataBlock` (the data block, cited to Litinski arXiv:1808.02892,
  page 7 Fig. 9) — **does not match its citation**: the paper states
  `1.5n+3` tiles (confirmed in three separate places in the paper plus an
  independent HTML cross-check); Qualtran's code computes `ceil(1.5n)`,
  dropping the `+3`. This **doubles** the data-block qubit count understatement
  for small `n_algo_qubits` — for our own `bell_and_t` example, Qualtran
  reports 1,734 data-block qubits where the cited paper's formula gives
  3,468, making the reported total `n_phys_qubits` (2,880) a ~38% undercount
  of the paper-correct total (4,614) (§8).

Net: this is no longer just "half verified, half taken on trust" — it's
"verified, and two of the three Litinski-sourced pieces have real,
reproducible gaps against their own citations." See `VERIFICATION.md` §9 for
the full itemized table.

**Update (2026-09-01): both issues filed upstream, and one patched locally.**

Both findings are now filed against Qualtran:
- [quantumlib/Qualtran#1943](https://github.com/quantumlib/Qualtran/issues/1943)
  — `CompactDataBlock` missing the `+3` tile constant.
- [quantumlib/Qualtran#1944](https://github.com/quantumlib/Qualtran/issues/1944)
  — the composite preset using Beverland's `a=0.03` instead of Litinski's
  own `a=0.1` for the factory's error model.

Both are open, unfixed, as of this writing. Rather than leave our own
published numbers silently wrong while waiting on upstream, we did two
things:

**Part A — always-on caveats (regardless of the Part B decision below).**
`README.md`'s example output now carries a visible caveat block naming both
issues with the specific numbers. `EstimateResult.__str__` (`estimate.py`)
appends the same caveats to every printed `scheme="beverland"` result, not
just to documentation — so anyone running the tool sees them, not just
README readers.

**Part B — the decision on whether to locally correct the underlying
numbers, not just warn about them: patch #1943, do not patch #1944.**
This was deliberately *not* a symmetric decision — the two issues are
different in kind, and treating them the same would have been the lazier,
worse answer:

- **#1943 is patched** (`src/guppy_estimand/_qualtran_patches.py`,
  `CorrectedCompactDataBlock`, wired in via `estimate._make_beverland_model`
  whenever `scheme="beverland"` and `data_block_name` is the default
  `"compact"`). Reasoning: this is an unambiguous transcription bug. The
  cited paper states one formula (`1.5n+3` tiles), confirmed identically in
  three separate places in the paper plus an independent HTML
  cross-check, and Qualtran's code computes a different, simpler formula
  that happens to be missing exactly the additive term. There is one
  correct fix, we're confident in it, and the override is small, thin, and
  clearly scoped (a 6-line method override, not a monkey-patch of
  Qualtran's own classes).
- **#1944 is deliberately *not* patched.** Reasoning: unlike #1943, this
  isn't a transcription error with one obviously correct answer — it's a
  genuine cross-paper composability question. Beverland's paper doesn't
  specify a magic-state factory at all (it has its own PSSPC/Table III
  method instead), and Litinski's paper doesn't specify a hardware/QEC
  threshold to combine with Beverland's assumptions. Qualtran's current
  choice — one consistent logical-error-rate constant applied across both
  the data block and the factory — is a defensible design (a single
  self-consistent hardware/threshold assumption for the whole device), even
  though it diverges from the specific numeric example in Litinski's own
  paper (which was written assuming *his* `a=0.1`, in isolation, not
  composed with Beverland's hardware assumptions at all). Patching this
  locally would mean asserting our own opinion of "correct cross-paper
  composition" in place of Qualtran's, with no stronger claim to being
  right — and unlike #1943, the upstream issue may reasonably be closed
  "won't fix" / "working as intended" rather than accepted as a bug. The
  Part A caveat (a visible, specific "~4.9x understated, see #1944" note)
  already satisfies "not silently misleading" for this one without taking
  on that judgment call or the associated maintenance burden.

**Numbers, before/after** (`bell_and_t` example, `d=17`, `scheme="beverland"`,
default `data_block_name="compact"`):

| Field | Before (raw Qualtran, unpatched) | After (this project's `estimate()`, #1943 patched) |
|---|---|---|
| `n_phys_qubits` | 2,880 | **4,614** (paper-correct; matches `VERIFICATION.md` §8's hand computation exactly) |
| `duration_hr` | 1.700e-08 | 1.700e-08 (unaffected — the tile-count bug doesn't feed into the cycle-count formula) |
| `error` | 2.035e-05 | 2.036e-05 (tiny increase — the corrected tile count slightly increases the data-block's error contribution; **still the #1944-understated value**, not Litinski's own `a=0.1` number) |

**Removing the #1943 patch once fixed upstream:** do not remove
`CorrectedCompactDataBlock` on a version bump alone.
`tests/test_qualtran_patches.py::test_upstream_qualtran_still_has_the_1943_bug`
asserts Qualtran's own (unpatched) `CompactDataBlock` still returns the
known-buggy tile count; if a future `qualtran` upgrade fixes #1943, that
test will start failing — check Qualtran's CHANGELOG/release notes for a
real landed fix (not a "won't fix" close) before deleting the override and
switching `_make_beverland_model` back to Qualtran's own `CompactDataBlock`.

Verified end-to-end by hand (2026-08-30, qualtran 0.7.0):
```python
from qualtran.resource_counting import GateCounts
from qualtran.surface_code import AlgorithmSummary, PhysicalCostModel

gc = GateCounts(t=1, toffoli=1, clifford=3, rotation=1, measurement=3)
alg = AlgorithmSummary(n_algo_qubits=3, n_logical_gates=gc)
PhysicalCostModel.make_gidney_fowler(data_d=17).n_phys_qubits(alg)   # -> 150794
PhysicalCostModel.make_beverland_et_al(data_d=17).n_phys_qubits(alg) # -> 4036
```
Both models ran without error and returned qubit counts of the right order
of magnitude for a surface-code-encoded few-qubit algorithm at d=17. This
is not a claim that these specific numbers are "correct" for a real
algorithm — d=17 and GateCounts here are arbitrary test inputs, not tied to
a target error budget — just that the pipeline works and is exercising the
real cost-model code, not a stub.

**Bench-Q** (Zapata, DARPA-funded, https://github.com/zapatacomputing/benchq):
read the actual source (`examples/ex_1_from_qasm.py`,
`src/benchq/conversions/_circuit_translations.py`). Findings:
- Input is a fully-flattened static circuit: `Union[QiskitCircuit, CirqCircuit,
  OrquestraCircuit]`, typically loaded from QASM via Qiskit.
- The estimation pipeline is a heavy graph-state compiler ("ruby slippers")
  that additionally requires a Julia installation.

**Why Qualtran over Bench-Q:** guppy programs can have classical control
flow (loops, conditionals, mid-circuit-measurement-dependent branching) that
doesn't reduce to a static flat gate list in general — flattening to
QASM/Qiskit for Bench-Q would be a lossy, harder translation than extracting
gate counts (which, per Qualtran's `SymbolicInt`, can even stay symbolic in
a loop trip count). Bench-Q's Julia dependency is also a heavy footprint for
what would be a lossy step. Qualtran's `GateCounts` input is both a smaller
target to build and a better structural fit for guppy's programming model.

### Confirming the gap

Searched Quantinuum/guppylang, Quantinuum/hugr, Quantinuum/selene,
Quantinuum/tket2 on GitHub (issues + code search) for "resource estimation",
"qubit count", "resource_estim" (2026-08-30): no existing tooling or open
discussion found. One tangentially related open issue:
Quantinuum/tket2#1597 ("Add hugr ops for additional quantum ops") — not
resource-estimation, just op coverage.

Also noted: `Quantinuum/hugr-qir` (HUGR → QIR) exists and is actively
maintained, confirming HUGR has precedented external conversion paths in
general — but QIR (LLVM IR) is a harder thing to gate-count-walk than HUGR
itself (would need an LLVM IR parser), so we go directly from HUGR rather
than via QIR.

## Environment / versions actually used

- guppylang **1.0.2** (not the 0.21.x seen in some cached docs/search
  results — check installed version directly, don't trust search snippets;
  `pip show guppylang`).
- hugr (Python package) **0.18.5**.
- qualtran **0.7.0**.
- Python **3.12.13** (via `py -V:Astral/CPython3.12.13`). **Python 3.14.5**
  (the machine's default `python`) has no prebuilt wheels for parts of this
  stack as of 2026-08-30 and pip's dependency resolver/source build hung
  for 10+ minutes; switched to 3.12 and installs completed normally within
  seconds-to-a-minute. If you hit a stuck `pip install`, check your Python
  version first.

## HUGR quirks hit while building this (verified by hand, not assumed)

- A compiled guppy function's `.compile()` returns a `hugr.package.Package`
  with a `.modules` list of `hugr.Hugr` objects (one module, in the cases
  tested).
- `Hugr.nodes()` returns `Iterable[tuple[Node, NodeData]]` — **not** just
  `Node`s. (`hugr[node]` on a bare `Node` works; `hugr[node_data_tuple]`
  does not — learned this from a live `AttributeError`.)
- Each quantum gate appears as a `hugr.ops.ExtOp`. Its **method**
  `op.name()` (not an attribute — `op.name` alone is a bound method object,
  confirmed by accidentally printing one) returns a qualified name like
  `"tket.quantum.H"`, `"tket.quantum.Rz"`, `"tket.quantum.MeasureFree"`.
  We classify gates by this qualified string; see
  `src/guppy_estimand/gate_counts.py` for the full table.
- **`if`/`else` in a guppy function compiles to a HUGR `CFG` with
  `DataflowBlock` children, not a `Conditional` node.** Verified directly:
  compiling
  ```python
  if b:
      h(q)
  else:
      x(q)
  ```
  produced node types `['... CFG', 'DataflowBlock', 'ExitBlock',
  'DataflowBlock', 'DataflowBlock', ...]` under `hugr.descendants(entrypoint)`
  — no `Conditional` node appeared. (A trivial `if True: ... else: ...` gets
  entirely constant-folded away by guppylang's optimizer and produces no
  branch structure at all — don't use that as a control-flow test case, it
  proves nothing. Use a runtime-dependent condition, e.g. branching on a
  measurement result.)
- `hugr.Hugr.children(node)` only returns *direct* children — for a
  guppy function's entrypoint, this misses everything inside a `CFG`'s
  `DataflowBlock`s. **`hugr.Hugr.descendants(node)` recurses fully** and is
  what `gate_counts.py` uses. Verified: `children(entrypoint)` on a
  conditional example found 0 gate ops; `descendants(entrypoint)` found all
  of them (`QAlloc`, `H`, `X`, `MeasureFree`, `Read`, `QFree`).
- Because of the above, **v1 deliberately refuses to estimate any program
  containing a `CFG`/`Conditional`/`TailLoop` node** rather than silently
  producing a wrong number: summing gate counts over all descendants of a
  branchy/looping program would double-count mutually-exclusive branches
  and undercount loop bodies run more than once. See README "Known
  limitations".
- `rz(qubit, angle)` needs a `guppylang.std.angles.angle` value, not a
  Python `float` — passing a raw `float` is a compile-time type error
  ("Expected argument of type `angle`, got `float`"). Use
  `guppylang.std.angles.pi` or `angle(...)`.
- `measure(q)` returns a `Measurement`-typed value, not `bool` — you can't
  `return` it from a `-> bool` function directly. There's a separate
  `tket.measurement.Read` op that converts `Measurement -> bool`.
- Every qubit variable must be consumed (measured or `discard`ed) before
  the function returns — an allocated-but-unconsumed `qubit()` is a
  compile error ("Drop violation... non-droppable type `qubit` is leaked").
- `inspect.getsourcelines` (used internally by guppylang to parse the
  decorated function's AST) fails with `OSError: could not get source code`
  if the `@guppy` function is defined via `python -c` / exec'd from a
  string rather than a real `.py` file on disk. Always compile from an
  actual file when testing.

## Known limitations (see README for the user-facing version)

- Straight-line (control-flow-free) guppy programs only, by design (see
  above).
- `data_d` (surface-code distance) is a caller-supplied parameter, not
  auto-selected to hit a target logical error rate.
- Any quantum op not in `gate_counts.py`'s classification tables raises
  `UnrecognizedGate` rather than being silently dropped.

## Possible future work (not started)

- Support straight-line-with-known-bounds control flow: e.g. accept a
  caller-supplied loop trip count and multiply the loop body's gate counts,
  or compute a worst-case (all-branches-summed) upper bound for
  conditionals with an explicit `--upper-bound` flag so the number is
  honestly labeled as a bound rather than an estimate.
- Auto-select `data_d` for a target total error budget (bisection over
  Qualtran's `model.error()`).
- `hugr-qir`-based cross-check: independently estimate from the QIR output
  and compare, as a consistency check on the direct-HUGR gate-count walker.
