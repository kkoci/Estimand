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
practical quantum advantage" (arXiv:2211.07629). We did not re-derive or
independently re-verify this equation against the paper — we are trusting
Qualtran's (Google's) implementation and citation, which is a published,
maintained, widely-used library, not a search snippet. If bit-for-bit
fidelity to the paper matters later, that citation is the place to check
first.

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
