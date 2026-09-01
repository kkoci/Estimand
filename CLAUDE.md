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

**Update (2026-09-02), added while building bounded control-flow
support (`upper_bound=True`, see below) — verified by hand against
compiled examples, not assumed from the note above (which was written
against a single if/else and never checked composition, loops, or the
optimizer's effect on repeated gates):**

- **A guppy function's `if`/`else` blocks all share ONE `CFG` per
  function, not one `CFG` per conditional.** Two sequential, independent
  `if`/`else` statements in the same function produce a *single* `CFG`
  node whose children include *all* `DataflowBlock`s from *both*
  conditionals as siblings (verified: 7 `DataflowBlock`/`ExitBlock`
  children for a 2-conditional function, not 2 separate `CFG`s). Grouping
  by "children of the CFG" tells you nothing about which blocks pair up as
  branches of which conditional — you have to follow the actual
  control-flow edges. **`Hugr.output_neighbours(node)` gives a
  `DataflowBlock`'s successor block(s)** (confirmed via a live example: a
  branch-point block had 2 successors, a straight-line/merge block had 1,
  `ExitBlock` had 0) — this is the edge accessor `gate_counts.py`'s bounded
  walker uses to reconstruct the actual branch/merge graph.
- **Loops do NOT compile to a `TailLoop` node in guppylang 1.0.2 / hugr
  0.18.5.** Both `while` and `for ... in range(...)` were compiled and
  inspected directly; neither produced a `TailLoop` anywhere in the HUGR.
  Instead:
  - `while` compiles to a `CFG` with a genuine **cycle**: a `DataflowBlock`
    branches back to an earlier `DataflowBlock` (verified:
    `output_neighbours` on the loop body block returned the *header*
    block, confirming a back edge). The header block itself contains the
    loop-condition check, wrapped in a `Conditional`/`Case` pair that
    produces the `Some`/`None`-tagged value the CFG branches on — this
    `Conditional` is boilerplate for encoding the branch decision, not a
    second "real" conditional.
  - `for ... in range(...)` is structurally more complex: it produces a
    **nested `CFG`** (a second `CFG` node inside a `DataflowBlock`/`Case`
    of the outer one) plus extra `Conditional`/`Case`/`prelude.panic`
    machinery for the iterator's `Option`-unwrap protocol
    (`MakeTuple`/`UnpackTuple` for the `(start, stop, step)` state,
    `arithmetic.int.*` comparisons, a `panic` case for the
    "unwrap on `None`" branch that should be unreachable). **This shape is
    not supported by the bounded walker** (raises
    `UnsupportedControlFlowShape`) — only single-CFG, single-back-edge
    `while`-style loops are handled. This is a deliberate scope decision,
    not an oversight: handling the nested-CFG/iterator-protocol shape
    correctly would need its own separate hand-verification pass.
  - Because loops are CFG back edges rather than an explicit node type,
    **a loop is keyed, for `loop_trip_counts`, by the HUGR node ID of its
    header block** (the back-edge *target*) — chosen over "order of
    appearance" because node IDs are unambiguous by construction (no
    debate about DFS traversal order for loops nested under different
    conditional branches), and the tool tells the caller the exact ID to
    use via `LoopTripCountMissing`'s error message, so opacity of raw node
    IDs isn't a practical usability problem.
  - `ops.TailLoop` is kept as an explicit, deliberately-unsupported case
    (`UnsupportedControlFlowShape`) in the bounded walker rather than given
    speculative handling — since no real example was ever observed, any
    handling written for it would be a guess, which this project's
    correctness bar doesn't allow. If a real `TailLoop` ever shows up
    (a different guppylang version, or hand-constructed HUGR), it needs
    its own hand-verification pass before being supported.
- **`compile()` applies an optimization pass by default
  (`OptimizationLevel.Default`) that cancels repeated identical adjacent
  gates.** Verified directly: `x(q0); x(q0); x(q0)` compiles down to a
  *single* `X` op, not three. `h(q0); x(q0); h(q0)` (non-adjacent-repeat,
  mixed gate types) survives intact as 3 separate ops. This is a second,
  distinct optimizer trap beyond the already-documented "`if True`
  constant-folds away" one above — **when writing a test that needs N
  literal gate ops to survive compilation, don't write the same gate N
  times in a row; use a mix of distinct gate types, or verify the actual
  compiled op count directly rather than assuming the source line count.**
  This cost real debugging time while building `tests/test_bounded_control_flow.py`
  (a test's "else branch has 3 clifford ops" assumption was silently wrong
  by a factor of 3 until this was traced down).
- A CFG's **entry block is its first child** in `Hugr.children(cfg_node)`
  order (a HUGR structural invariant: the CFG's own input signature must
  match its entry block's), **not** "whichever child block has no
  predecessor." The naive in-degree-0 heuristic is wrong whenever the
  function body's very first statement is a loop (no straight-line code
  before the `while`): the entry block IS the loop header in that case,
  and has an *incoming* back edge from the loop body, so it does NOT have
  in-degree 0. Learned this from a live, reproducible test failure before
  switching to the first-child rule.

**Update (2026-09-03), nested loops — verified by hand, and a real bug
found and fixed, not just confirmed-correct-by-luck:**

- **A `while` loop nested inside another `while` loop still compiles to
  ONE CFG** (no nested `CFG` node — unlike `for`-over-an-iterator, which
  does nest). Verified directly: compiling
  ```python
  i = 0
  while i < 3:
      j = 0
      while j < 2:
          h(q0)
          j += 1
      i += 1
  ```
  produced a single `CFG` node with 6 `DataflowBlock`/`ExitBlock` children
  and exactly two back edges in its block graph — inner `44 -> 29` and
  outer `53 -> 5` (concrete node IDs from one compile; renumber per
  program). The inner loop's entire node set `{29, 44}` was, as expected,
  absorbed into the outer loop's natural-loop node set (`_natural_loop_nodes`
  computed `{5, 53, 29, 22, 44}` for the outer header) — the outer loop's
  body legitimately contains a second, independent loop structure inside
  it, not a special case requiring different back-edge detection.
- **This exposed a real bug**, not just an unverified gap: `_walk_cfg`'s
  `dp_within` helper (the restricted DP used for "cost of one pass through
  an outer loop's body") did not check whether a node it was visiting was
  itself a *different* loop's header. It only ever filtered out the
  *outer* loop's back-edge target from a node's successors — so when
  traversal reached the inner loop's header (node 29 above) mid-body, that
  node's own back edge (`44 -> 29`) was never excluded (`dp_within`'s
  exclusion list only ever contained the *outer* header, 5), and the walk
  recursed `29 -> {53, 44}`, then `44 -> 29`, forever. **Confirmed
  empirically as a `RecursionError`** (not a hand-derived guess) by
  running `extract_gate_counts(..., upper_bound=True, loop_trip_counts={outer: 1})`
  on the nested-loop example above before any fix was applied.
- **Fix**: `dp_within(node, stop_header)` now checks `node in headers and
  node != stop_header` first. If true (a nested loop's header), it fully
  unrolls that inner loop — its own trip count, its own recursive
  `dp_within` call scoped to *its own* header as the new stop point — and
  only then continues traversal (still bounded by the original
  `stop_header`) from the inner loop's exit successor. Because the
  caller (`dp`, for the outer loop) scales `dp_within`'s entire return
  value by the *outer* trip count, and the inner unrolling inside
  `dp_within` already scales the inner body by the *inner* trip count, an
  innermost loop body's gates end up correctly scaled by
  `outer_trip * inner_trip` — verified against the actual walker output
  across `(outer_trip, inner_trip)` pairs including `(0, N)` and `(M, 0)`
  edge cases, all matching the product exactly, in
  `tests/test_bounded_control_flow.py::test_nested_loop_no_longer_crashes_and_scales_inner_body_by_product`.
  A gate in the outer body but *outside* the inner loop was separately
  confirmed to scale by `outer_trip` alone, in the same program as an
  inner-loop-body gate scaling by the product — see
  `::test_nested_loop_outer_only_gates_scale_by_outer_trip_alone`, chosen
  specifically to catch a fix that collapses this distinction (e.g.
  scaling the whole outer body uniformly by the product).
- **`loop_trip_counts` keying stays unambiguous for nested loops**: the
  inner and outer headers are different HUGR node IDs by construction (no
  special-casing needed to keep them distinct), and `LoopTripCountMissing`
  correctly names *whichever* header is actually missing — the outer
  header first if nothing has been supplied yet (since `dp` checks its own
  header before recursing into `dp_within` for the body), then
  specifically the inner header once the outer count has been supplied but
  the inner hasn't. Verified via
  `::test_nested_loop_missing_trip_count_names_whichever_header_is_missing`
  (not assumed from the single-loop error-message behavior).
- **The single-loop `n_qubits`-not-scaled reasoning extends unchanged to
  nested loops**, verified rather than assumed: a qubit allocated (and
  freed) fresh each *innermost* iteration was confirmed to still count
  once overall (`n_qubits == 1`), not `outer_trip * inner_trip` times —
  because `_scale_gates_only` is applied at *every* nesting level
  (including the new nested-header branch inside `dp_within`) and never
  touches `.n_qubits` at any level, the non-scaling composes automatically
  without needing separate reasoning per nesting depth. See
  `::test_nested_loop_qubit_allocated_in_inner_body_not_scaled_by_either_trip`.
- Composition with the pre-existing (already-tested) conditional-max
  logic was also checked with a conditional inside the inner loop's body,
  confirmed to scale the heavier branch's gates by `outer_trip *
  inner_trip` — see `::test_nested_loop_composes_with_conditional_in_inner_body`.
  This wasn't a given: the fix only touches the *nested-header* branch of
  `dp_within`, so confirming it doesn't interact badly with the
  *branch-point* (non-header, `len(succs) > 1`) branch of the same
  function was worth checking explicitly rather than assuming they don't
  interfere with each other.

## Known limitations (see README for the user-facing version)

- Straight-line (control-flow-free) guppy programs only, by default. See
  "Bounded control flow (opt-in)" below for the `upper_bound=True`
  alternative added 2026-09-02, which is scoped and limited, not a full
  replacement.
- `data_d` (surface-code distance) is a caller-supplied parameter, not
  auto-selected to hit a target logical error rate.
- Any quantum op not in `gate_counts.py`'s classification tables raises
  `UnrecognizedGate` rather than being silently dropped.

## Bounded control flow (opt-in) — added 2026-09-02

Implements the "possible future work" item below: `extract_gate_counts()`
and `estimate()` accept `upper_bound: bool = False` and
`loop_trip_counts: dict[int, int] | None = None`. This is an **opt-in
alternative**, not a replacement for the default straight-line-only path
(which is unchanged and still raises `ControlFlowNotSupported`).

**What `upper_bound=True` does:**
- Every conditional (`if`/`else`, and any HUGR `Conditional` node
  encountered, including the boilerplate ones a `while` loop's condition
  check compiles to) contributes the **max** of its branches' gate counts
  — not the sum — since only one branch ever executes. Verified correct
  for **sequential, independent conditionals** specifically (not just a
  single conditional in isolation): two sequential `if`/`else` blocks in
  one function share a single CFG (see "HUGR quirks" above), so the
  implementation does real graph analysis (DFS + a longest-weighted-path
  DP over the CFG's block graph, max at each branch point) rather than
  naively summing or maxing over "all DataflowBlock children of the CFG"
  as one flat set — see `tests/test_bounded_control_flow.py::test_sequential_independent_conditionals_sum_of_max_per_conditional`,
  which is deliberately constructed so "sum of max-per-conditional",
  "sum of all branches", and "max of all branches" are three different
  numbers, to catch exactly this class of bug.
- Every loop (a CFG back edge — see "HUGR quirks" above; NOT a `TailLoop`)
  requires a caller-supplied trip count, keyed by the loop header's HUGR
  node ID in `loop_trip_counts`. **Gate counts are multiplied by the trip
  count; `n_qubits` is not.** This is a deliberate, documented modeling
  choice (`gate_counts.py::_scale_gates_only`): guppy's linear qubit typing
  forces a qubit allocated inside a loop body to be freed within the same
  iteration (an allocated-but-unconsumed qubit is a compile error — see
  "HUGR quirks" above), so a loop is assumed to reuse one physical qubit
  slot across iterations rather than needing `trip_count` distinct ones.
  If a future guppy version or usage pattern breaks that assumption (a
  qubit that somehow outlives one iteration), this would need revisiting —
  nothing in the current HUGR walk detects that case.
- Missing a trip count for a loop that's present raises
  `LoopTripCountMissing`, naming the loop's header node ID — never
  defaulted to 1 or guessed.
- Composition (loop containing a conditional, conditional containing a
  loop) is handled by the same general recursive algorithm, not special
  cased — see `tests/test_bounded_control_flow.py::test_loop_containing_a_conditional`
  and `::test_conditional_containing_a_loop`.
- **Nested loops** (a `while` inside another `while`) are supported: the
  inner loop's body gates scale by the *product* of both trip counts,
  gates in the outer body but outside the inner loop scale by the outer
  trip count alone, and `loop_trip_counts` keying / `LoopTripCountMissing`
  stay unambiguous per loop. This was not free — see "HUGR quirks"
  (2026-09-03) for a real `RecursionError` bug this found and fixed in
  `dp_within`, not just a gap that happened to already work.
- `EstimateResult.is_upper_bound` and its `__str__` explicitly say
  "UPPER BOUND -- NOT a point estimate" and annotate each affected field,
  rather than returning a number that looks like a normal estimate.

**What's explicitly NOT supported** (raises `UnsupportedControlFlowShape`
rather than silently guessing): `for` loops over an iterator (nested
CFG + iterator-protocol machinery — see "HUGR quirks" above), a loop with
more than one back edge into the same header, a loop header without
exactly one "into the loop" and one "exit" successor, a loop body with an
internal early exit (e.g. `break`), and `TailLoop` nodes. **Update
(2026-09-04): "never observed produced" for `TailLoop` no longer holds
unconditionally** — a real qshelf program showed it IS produced, for the
`array(x for _ in range(n))` array-comprehension idiom specifically (not
for plain `while`/`for` statements, where the original claim still holds).
See "Real-world stress test" below. Each of these unsupported shapes would
still need its own hand-verification pass, per this project's correctness
bar, before being supported — none has been done, including for the
now-confirmed-real `TailLoop` case.

**Update (2026-09-05): calling a non-inlined function is no longer in this
"not supported" list.** It was, briefly (`CallNotSupported`, added
2026-09-04, after the same real-world stress test found it as a genuine
silent undercount — the most serious finding of that pass, more serious
than the `TailLoop` case above). It is now followed and walked instead —
see "Call-following" below for the fix, the trip-count composition design
across call boundaries, and the qshelf re-run. `CallNotSupported` still
exists, narrowed to the genuinely irresolvable case (`CallIndirect`, or a
`Call` targeting a `FuncDecl`); a new exception,
`RecursiveCallNotSupported`, covers a cyclic call graph.

## Real-world stress test (2026-09-04): QFT from kkoci/Qshelf

Everything above was built and verified against hand-written, synthetic
examples. This section runs `guppy_estimand` against a real,
independently-authored algorithm for the first time — [kkoci/Qshelf](https://github.com/kkoci/Qshelf)'s
QFT implementation (`packages/qft`) — as a stress test of the whole
pipeline, following the same "verify by hand, don't assume" discipline as
everything else in this file. It found two real, previously-unknown gaps,
which is exactly the kind of thing this exercise was for.

**Step 0 — version check.** qshelf's every package pins `guppylang==1.0.2`
(`packages/*/pyproject.toml`), exactly matching this project's installed
version (see "Environment / versions actually used" above). No version
mismatch to account for; tested directly against the installed toolchain.

**Step 1 — confirming QFT is a reasonable first candidate.** Read
`packages/qft/src/qft/qft.py` directly rather than assuming its shape from
the package name. Found: `qft[n](qs: array[qubit, n])` is decorated
`@guppy.comptime(daggerable=True)` and generic over the register size `n`,
with two nested Python-level `for` loops (a rotation cascade: `for i in
range(n): h(qs[i]); for j in range(i+1, n): crz(...)`) plus a final swap
pass (`for k in range(n//2): swap(...)`). `iqft` (the inverse) exists in
the same file but was NOT used, per the landmine noted in the task that
motivated this exercise: Quantinuum/guppylang#2250, a real, documented,
unrelated guppylang bug where `iqft` produces a wrong unitary compiled
standalone vs. combined with `qft`. Only `swap` and `qft` were vendored
into `examples/_qshelf_qft.py` (verbatim, with an attribution header).

**Step 2 — the actual compiled HUGR structure (verified by hand, several
surprises).** Compiled a `main()` calling `qft(qs)` on a small register and
inspected the result directly (`hugr.nodes()`, `hugr.children()`,
`hugr.output_neighbours()`, `hugr.descendants()` — same tools as every
prior verification pass). Findings, in the order they were hit:

1. **The idiomatic array construction, `array(qubit() for _ in range(N))`
   (exactly what qshelf's own `examples/basic_qft.py` uses), compiles to a
   `TailLoop` node.** This is the first time this project has ever
   observed a real `TailLoop` — every prior verification (see "HUGR
   quirks" above) found plain `while`/`for` *statements* compile to a CFG
   with a back edge instead. The two are compiled differently: an
   array-comprehension is lowered via `TailLoop`, an ordinary loop
   statement is not. `guppy_estimand`'s bounded walker explicitly refuses
   `TailLoop` (no verified handling exists for it), so this raises
   `UnsupportedControlFlowShape` immediately — confirmed by actually
   running it, not inferred from the node type alone.
2. **Switching to a literal array construction, `array(qubit(), qubit(),
   qubit())`, avoids the `TailLoop`** (confirmed: the node type histogram
   for the compiled HUGR no longer contains `TailLoop` at all). What's left
   is a `CFG` with a single back edge (matching the already-verified
   while-loop-containing-a-conditional shape) plus several `Conditional`
   nodes — all inside `guppylang.std.quantum.discard_array`'s own body, NOT
   inside `qft` (see point 4). `qft`'s OWN contribution to `main`, at small
   n, turned out to be **pure straight-line dataflow** — its two `for`
   loops are fully unrolled at compile time by `@guppy.comptime`
   specialization for a statically-known `n`. This means the bounded-mode
   work (conditional upper bounds, loop trip counts, nested-loop handling)
   was **not actually exercised by QFT's own algorithmic structure at
   all** — a genuinely useful, if slightly deflating, finding: `upper_bound=True`
   was needed here only because of *unrelated* array-handling machinery,
   not because QFT itself has runtime-dependent control flow.
3. **`collections.borrow_arr.*` ops (array-indexing/construction
   bookkeeping for linear qubit arrays) are not `tket.*`-namespaced.** The
   bounded walker's existing "skip any non-`tket.` ExtOp" rule (originally
   justified only for classical loop-condition/iterator-protocol
   bookkeeping — see "HUGR quirks" above) turned out to also cover these,
   which was not something it was designed or verified for. It happens to
   be safe (these ops are array bookkeeping, not physical operations), but
   the straight-line walker has no equivalent allowance and raises
   `UnrecognizedGate` on them — meaning **a genuinely straight-line guppy
   program that uses `array[qubit, n]` indexing cannot currently be
   estimated in default mode at all**, only in `upper_bound=True` mode
   (which tolerates it only as a side effect of a rule meant for something
   else). Not fixed in this pass; noted as a real gap below.
4. **A real, serious bug: calls to non-inlined functions were silently
   invisible.** `discard_array(qs)` (used by literally every qshelf
   example/test to free a qubit array) turned out to compile as a call to
   a *separately-compiled* `FuncDefn`, not inlined — confirmed via
   `hugr.children()`/`f_name` lookups, and confirmed that
   `Node(<that FuncDefn's id>) in hugr.descendants(hugr.entrypoint)` is
   `False`: the callee's entire body, including a real `tket.quantum.QFree`,
   is unreachable from `main`'s own subtree. Neither walker followed
   `ops.Call` edges — a `Call` node was simply skipped (not `ops.ExtOp`,
   not a recognized control-flow op, no branch handled it at all). For
   `discard_array` specifically the numeric impact happened to be nil
   (its only quantum op, `QFree`, is in `_IGNORED` and contributes 0
   regardless) — but this was luck, not correctness.
5. **The luck ran out at register size 4.** Swept `n = 2..6` (fresh
   subprocess per `n`, checking `FuncDefn` names in the compiled HUGR
   directly): `qft` itself is inlined into `main` for `n <= 3`, but
   compiled as a **separate, called `FuncDefn`** for `n >= 4` — with zero
   other code change, purely a function of the register size crossing some
   compiler-internal inlining threshold. Before any fix, calling
   `extract_gate_counts(upper_bound=True, ...)` on the `n=4` program
   **silently returned `GateCounts()` (all zero) plus only the 4 directly-
   visible `QAlloc`s** — i.e., it reported that QFT does *nothing*, with
   no exception, no warning. This was only caught because of this
   project's own stated discipline: sanity-checking the walker's output
   against a hand-derived expectation (4 qubits → 4×H + 6×CRz from the
   cascade + 2 swaps × 3 CX = 10 clifford, 6 rotation) caught the
   all-zero result as implausible immediately. **This is the single most
   serious finding of this stress test**: a real, natural, idiomatic
   real-world program at a realistic size (4+ qubits — nobody estimates a
   3-qubit QFT for its own sake) produced a confidently-wrong,
   plausible-looking number with zero indication anything was missing.

**Fix applied (2026-09-04): `CallNotSupported`.** Rather than leave this as
a silent gap (or, at the other extreme, attempt the much larger undertaking
of actually following `Call` edges into arbitrary callees — memoization
across FuncDefn boundaries, handling potential recursion — which is out of
scope for what this stress-test task asked for), both walkers now detect
`ops.Call` directly and raise a new exception, `CallNotSupported`, naming
the unreachable callee by resolving the `Call` node's static function-
pointer edge (`hugr.num_in_ports`/`linked_ports` on the last input port) to
the target `FuncDefn` and reading its `f_name`. This converts the silent
wrong-number failure mode into a loud, honest one — consistent with this
project's existing `ControlFlowNotSupported`/`UnrecognizedGate`/
`UnsupportedControlFlowShape` pattern of refusing to guess rather than
guessing wrong. It does **not** make QFT-at-4-qubits (or any call to a
non-inlined function) estimable — that's real future work, tracked below.
Regression tests: `tests/test_call_not_supported.py` (a minimal
`discard_array`-based repro, chosen because plain user-defined helper
functions were found to reliably get inlined at the sizes tried, while
`discard_array` reliably does not — so it's the smallest available reliable
trigger for the bug this guards).

**Step 3/4 — the actual reported result.** Working around both idioms
(literal array construction instead of the comprehension; individual
`discard()` per qubit instead of `discard_array`) keeps `n` at 3 (the last
size where `qft` is still inlined) and gives a fully working, hand-verified
result: `gate_counts = GateCounts(clifford=6, rotation=3)`, `n_qubits = 3`
— matching the hand-derived expectation (3×H + 3×CRz + one 3-CNOT swap)
exactly. Full `estimate()` output, and the three documented failure modes
run for real (not just described), are in `examples/qft_n.py` and
README.md "Real-world stress test".

**Honest bottom line**: QFT's own algorithmic structure is fine and needs
no bounded-mode support at all once compiled. What this stress test
actually found is two real gaps in `guppy_estimand` — a `TailLoop` shape
and, much more seriously, an entire class of silent undercount from
un-followed function calls — that no synthetic test had ever exposed,
because every synthetic test so far was a single self-contained function.
That is the primary, most valuable result of this exercise, not the
6-clifford/3-rotation number.

## Call-following (2026-09-05)

Replaces the blanket `CallNotSupported` stopgap from the real-world stress
test above with real call-following: both walkers now recurse into a
called function's own body using the same traversal that's walking the
caller, instead of refusing every non-inlined call. Same discipline as
every prior pass — HUGR structure verified by hand before any code was
written, not assumed.

**Step 1 — how `ops.Call` actually resolves to its target, precisely.**
Inspected the installed `hugr` 0.18.5 `ops.Call` class directly
(`inspect.getsource`), rather than assuming the earlier ad hoc "last input
port" heuristic (used by the original `CallNotSupported` for its error
message only, never load-bearing) was principled. Found:
`Call._function_port_offset()` returns `len(self.signature.body.input)` —
the count of ordinary dataflow input ports; the function-pointer edge (a
*static*, function-typed edge, not a regular dataflow edge) is the port
immediately after them, resolved via
`hugr.linked_ports(call_node.inp(offset))`. Confirmed the earlier "last
port" heuristic only coincided with this because `Call` has no other port
kinds beyond dataflow args + one function pointer — the principled offset
is used now (`_resolve_call_target` in `gate_counts.py`).

Also verified by hand, using `discard_array` at two different array sizes
compiled into one program: **calling the *same* instantiation of a
function from two different call sites resolves both `Call` nodes to the
*same* `FuncDefn` node** (guppylang does not duplicate the body per call
site) — this is what makes memoizing a callee's cost by its `FuncDefn`
node ID both correct and effective. Calling *different* instantiations of
a generic function (e.g. `discard_array` at array sizes 2 and 3) DOES
produce distinct `FuncDefn` nodes (observed names `discard_array$2` vs.
`discard_array$3`), confirmed by node ID, so this never conflates them.

Not otherwise relevant here, but checked: `ops.FuncDecl` (external/opaque
function declaration, no body in this compiled unit) and `ops.CallIndirect`
(a call whose target is a runtime dataflow value, not a static edge) both
exist as HUGR concepts. Neither was ever observed produced by any guppy
source pattern tried in this project — `CallNotSupported` is narrowed to
cover them as a documented, defensive case, not something independently
reproduced from real guppy code (see "What's not independently verified"
below).

`_as_hugr` still rejects multi-module `Package`s outright (unchanged,
pre-existing behavior), so whether a `Call` could ever target a `FuncDefn`
in a *different* module of a multi-module package never arises in this
codebase — noting this as an explicit non-issue rather than a silently
unconsidered case.

**Step 2 — the walker change, and the trip-count composition design
decision.** Both `_walk_region` (bounded mode) and the straight-line
walker (rewritten from a flat `hugr.descendants()` loop into a recursive
`_walk_region_straight_line`, structurally mirroring the bounded walker,
for the same reason bounded mode already uses `children()`-with-explicit-
recursion rather than `descendants()`) now handle `ops.Call` by resolving
the target and recursively walking it with the *same* walking function
(`_walk_call`, shared by both modes) — so a straight-line caller's callee
must itself be straight-line (raises `ControlFlowNotSupported` on any
control flow found anywhere in the call graph, not just directly in the
caller), and a bounded caller's callee gets the full conditional-max/
loop-trip-count treatment.

**Design decision, made explicit rather than left implicit (see
`_WalkCtx`'s docstring in `gate_counts.py` for the full reasoning)**:
`loop_trip_counts` stays a *flat* dict keyed by HUGR node ID — **not**
namespaced per call site. This falls directly out of the Step 1 finding
that the same instantiation shares one `FuncDefn`: a loop inside a callee
has one fixed, globally-unique header node ID no matter how many places
call it, so no new keying scheme was needed. What this gets right
automatically, with zero special-casing: call the same function once
outside a loop and once inside a caller-side loop with trip count `N`, and
its cost is added once at `1x` and once at `Nx` — each call site's own
surrounding structure (loop, conditional, or neither) multiplies the
callee's memoized-but-recomputed-per-site cost independently, because
`func_memo` only avoids *recomputing* a callee's walk, never avoids
*re-adding* it once per call site that reaches it. The one real limitation
this implies, documented rather than hidden: if the same callee is called
from multiple sites and its own internal loop should truly run a different
number of times depending on which site called it, that cannot be
expressed — one node ID, one trip count, applied everywhere that loop is
reached.

Recursion is guarded via a `call_stack: frozenset` threaded through the
same context object (`_WalkCtx`), containing every `FuncDefn` currently
being walked on the path from the entrypoint. A `Call` whose target is
already in `call_stack` raises `RecursiveCallNotSupported` naming the
cycle, checked *before* any recursive walk is attempted (not caught via
Python's own `RecursionError`, and not silently masked by memoization
returning a stale/incomplete result).

**Step 3 — repeated calls to the same function, verified with a dedicated
test, not just reasoned about.** Built a helper function called from two
different call sites in one program: once outside any loop, once inside a
caller-side `while` loop with a trip count. A plain, small user-defined
helper was found (by hand, empirically) to reliably get *inlined* by
guppylang regardless of size tried up to 32 gates across 2 call sites —
so, to get a genuinely non-inlined, fully-hand-controlled test callee (as
opposed to relying on a stdlib function's own, more complex internal
structure), a 100-clifford-gate helper was used, confirmed by hand to
still compile as a separate `FuncDefn`. Result:
`tests/test_call_following.py::test_same_callee_called_outside_and_inside_a_loop`
— gate count exactly `100 * (1 + trip_count)` for `trip_count` in
`{0, 3, 7}`, confirming the outside call contributes `1x` and the inside
call contributes `trip_count x` independently, not `2x` (which a naive
"memoize the whole answer, not just the callee's own cost" bug would give)
and not just `1x` (which would silently drop the loop multiplication for
the second call). A companion test
(`test_same_callee_memoized_not_recomputed_but_recounted_per_site`) calls
the same helper from three sites, all outside any loop, confirming `3x`
exactly — checking that memoization (avoiding re-walking the callee's
body) never becomes accidental de-duplication (undercounting how many
times its cost should be added).

**Step 4 — recursion, verified with a real recursive guppy function, not
a hypothetical.** guppylang does allow writing genuine recursion (checked
by hand, not assumed) — a function calling itself, and indirect/mutual
recursion (A calls B calls A), both compile and reach `.compile()`
successfully. A recursive function cannot be inlined by construction (no
finite inlining depth), so it reliably produces a real `Call` node
pointing back into a cycle, giving a clean, fully-controlled test case —
unlike the inlining-threshold guesswork needed for Step 3's non-recursive
tests. Both direct and indirect recursion are correctly detected and
raise `RecursiveCallNotSupported` in bounded mode
(`tests/test_call_following.py::test_direct_recursion_detected_in_bounded_mode`,
`::test_indirect_mutual_recursion_detected`).

**Honest nuance found, not glossed over**: for straight-line mode
specifically, the *same* recursive test program instead raises
`ControlFlowNotSupported` — because the recursive function's own base-case
check (an `if n > 0:`) is itself a HUGR `CFG`, which straight-line mode
refuses outright, before ever reaching the recursive `Call` node one level
deeper. This is not a coincidence specific to the example: any practical
recursive function needs a base case to terminate, which is expressed as a
conditional, so in practice straight-line mode is expected to always hit
`ControlFlowNotSupported` before `RecursiveCallNotSupported` for real
recursive guppy code. The recursion-cycle-detection code itself is shared
between both walkers (`_walk_call`) and is directly exercised by the
bounded-mode test above; the straight-line-mode test
(`::test_direct_recursion_in_straight_line_mode_fails_loudly_one_way_or_another`)
only confirms straight-line mode doesn't silently succeed or hang instead,
accepting either exception rather than asserting a specific one it cannot
actually reach.

**What's NOT independently verified**: `CallNotSupported`'s two remaining
narrow cases (`CallIndirect`, and a `Call` targeting a `FuncDecl`) have no
known guppy source pattern that produces them — `tests/test_call_following.py::test_call_not_supported_still_importable_for_opaque_calls`
is a smoke test that the exception class and its docstring exist, not a
HUGR-level repro of triggering either code path. Documented as an honest
gap rather than a fabricated test asserting behavior nobody has actually
exercised.

**Step 5 — re-running the qshelf QFT stress test, full honest result.**
Swept `n = 2..6` again (same registers as the original inlining-threshold
sweep), using the REAL idiomatic `discard_array(qs)` call throughout — no
workaround needed for it anymore — with a literal array construction
(`array(qubit(), qubit(), ...)`) still required, since the array-
*comprehension* idiom's `TailLoop` shape (found in the first pass) is a
completely separate HUGR shape that call-following does not touch and
remains unsupported. **Result: all five register sizes succeed and match
the closed-form hand-derived formula for QFT's structure exactly**:

```
H count     = n
CRz count   = n(n-1)/2        (triangular number: sum_{i=0}^{n-1} (n-1-i))
swap count  = n // 2          (each swap = 3 CX)
clifford    = H + 3*(n//2)  = n + 3*(n//2)
rotation    = CRz            = n*(n-1)/2
```

| n | clifford (H + 3⌊n/2⌋) | rotation (n(n-1)/2) | Walker output | Match |
|---|---|---|---|---|
| 2 | 2 + 3 = 5   | 1  | `clifford: 5, rotation: 1`   | exact |
| 3 | 3 + 3 = 6   | 3  | `clifford: 6, rotation: 3`   | exact |
| 4 | 4 + 6 = 10  | 6  | `clifford: 10, rotation: 6`  | exact |
| 5 | 5 + 6 = 11  | 10 | `clifford: 11, rotation: 10` | exact |
| 6 | 6 + 9 = 15  | 15 | `clifford: 15, rotation: 15` | exact |

`n_qubits` also matched `n` exactly at every size. `discard_array`'s own
internal loop needs a trip count (it has one — a real loop, discovered via
`LoopTripCountMissing` at every `n`), but the *value* supplied for it was
confirmed, by hand, not to affect the reported gate counts at all (checked
1, 4, and 100 all give identical output at `n=4`) — `discard_array`'s only
quantum op is `QFree`, which is `_IGNORED` (zero-cost) — so this doesn't
threaten the correctness of the table above, but it is worth noting as a
minor real-world usability wrinkle: a caller must still supply *some*
non-negative integer for that loop to get past `LoopTripCountMissing`,
even though, in this specific case, its value turns out not to matter.

Full `estimate()` output (physical qubits/runtime/error, scheme=beverland,
`d=17`) for all five sizes is in `examples/qft_n.py`'s actual run output
and README.md "Real-world stress test" — physical qubit count and runtime/
error all scale monotonically with `n`, as expected.

**Honest bottom line, updated**: call-following resolved the single most
serious finding from the first stress-test pass — QFT is now estimable at
every register size tested, using qshelf's own real, idiomatic
`discard_array` pattern, not a workaround. The array-comprehension
`TailLoop` gap from the first pass remains genuinely open (a different
problem this task was not asked to fix); `examples/qft_n.py` demonstrates
it still failing, for real, rather than silently dropping it from the
example now that the headline result looks better.

## Possible future work (not started)

- ~~Support straight-line-with-known-bounds control flow...~~ **Done,
  2026-09-02 — see "Bounded control flow (opt-in)" above.** Remaining gaps
  within that feature (not "future work" so much as known scope limits):
  `for`-loop/iterator support, loops with internal `break`, full `TailLoop`
  support (now confirmed reachable in practice, via array comprehensions —
  see "Real-world stress test" above; still unimplemented).
- ~~Follow `ops.Call` edges into non-inlined callees~~ **Done, 2026-09-05 —
  see "Call-following" below.** `CallNotSupported` is narrowed to
  genuinely irresolvable calls (`CallIndirect`, or a `Call` targeting a
  `FuncDecl`); an ordinary call to a defined function is now followed and
  walked, with recursion detected and refused as
  `RecursiveCallNotSupported`. Re-running the qshelf QFT stress test with
  this in place now succeeds across the full `n=2..6` range tested, using
  the real, idiomatic `discard_array(qs)` call — see "Real-world stress
  test" for the original finding and "Call-following" for the fix and
  re-run.
- Extend non-`tket.*`-ExtOp tolerance (currently bounded-mode-only, and
  only as a side effect of a rule designed for something else — see "Real-
  world stress test" point 3 above) to the straight-line walker too, so
  straight-line programs using `array[qubit, n]` indexing don't
  unnecessarily raise `UnrecognizedGate` on `collections.borrow_arr.*`
  bookkeeping ops.
- Auto-select `data_d` for a target total error budget (bisection over
  Qualtran's `model.error()`).
- `hugr-qir`-based cross-check: independently estimate from the QIR output
  and compare, as a consistency check on the direct-HUGR gate-count walker.
